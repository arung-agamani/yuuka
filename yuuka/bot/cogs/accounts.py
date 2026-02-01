"""
Accounts Cog for managing account groups and aliases.

Handles commands for creating account groups, managing aliases,
and resolving new account names to groups.
"""

import logging
from typing import Callable, Optional

import discord
from discord import app_commands
from discord.ext import commands

from yuuka.db import AccountGroup, LedgerRepository
from yuuka.models.account import AccountType

logger = logging.getLogger(__name__)


def format_account_type(account_type: AccountType) -> str:
    """Format account type with emoji."""
    type_emoji = {
        AccountType.ASSET: "💰",
        AccountType.LIABILITY: "📋",
        AccountType.EQUITY: "🏦",
        AccountType.REVENUE: "📈",
        AccountType.EXPENSE: "📉",
    }
    emoji = type_emoji.get(account_type, "📄")
    return f"{emoji} {account_type.value.title()}"


class AccountGroupSelect(discord.ui.Select):
    """Dropdown for selecting an account group."""

    def __init__(
        self,
        groups: list[AccountGroup],
        alias: str,
        repository: LedgerRepository,
        user_id: str,
    ):
        self.alias = alias
        self.repository = repository
        self.user_id = user_id
        self.groups = groups

        options = [
            discord.SelectOption(
                label=g.name[:100],
                value=str(g.id),
                description=f"{g.account_type.value.title()} - {g.description or 'No description'}"[
                    :100
                ],
                emoji=self._get_type_emoji(g.account_type),
            )
            for g in groups[:25]  # Discord limit
        ]

        super().__init__(
            placeholder=f"Select account group for '{alias}'",
            min_values=1,
            max_values=1,
            options=options,
        )

    def _get_type_emoji(self, account_type: AccountType) -> str:
        type_emoji = {
            AccountType.ASSET: "💰",
            AccountType.LIABILITY: "📋",
            AccountType.EQUITY: "🏦",
            AccountType.REVENUE: "📈",
            AccountType.EXPENSE: "📉",
        }
        return type_emoji.get(account_type, "📄")

    async def callback(self, interaction: discord.Interaction):
        try:
            group_id = int(self.values[0])
            group = next((g for g in self.groups if g.id == group_id), None)

            if not group:
                await interaction.response.edit_message(
                    content="❌ Account group not found.",
                    view=None,
                )
                return

            # Create the alias
            self.repository.add_account_alias(
                alias=self.alias,
                group_id=group_id,
                user_id=self.user_id,
            )

            await interaction.response.edit_message(
                content=(
                    f"✅ Alias created!\n\n"
                    f"**'{self.alias}'** → **{group.name}** ({group.account_type.value})\n\n"
                    f"Future uses of '{self.alias}' will automatically map to '{group.name}'."
                ),
                view=None,
            )
            logger.info(
                f"User {self.user_id} mapped alias '{self.alias}' to group '{group.name}'"
            )
        except Exception as e:
            logger.error(f"Error in AccountGroupSelect callback: {e}", exc_info=True)
            await interaction.response.edit_message(
                content=f"❌ Error creating alias: {str(e)}",
                view=None,
            )


class AccountGroupSelectView(discord.ui.View):
    """View containing the account group select dropdown."""

    def __init__(
        self,
        groups: list[AccountGroup],
        alias: str,
        repository: LedgerRepository,
        user_id: str,
    ):
        super().__init__(timeout=120.0)
        self.add_item(AccountGroupSelect(groups, alias, repository, user_id))
        self.alias = alias
        self.user_id = user_id

    @discord.ui.button(label="Create New Group", style=discord.ButtonStyle.secondary)
    async def create_new_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Show modal to create a new account group."""
        modal = CreateAccountGroupModal(
            alias=self.alias,
            repository=None,  # Will be set by cog
            user_id=self.user_id,
        )
        await interaction.response.send_modal(modal)

    async def on_timeout(self):
        logger.info(f"Account group selection timed out for user {self.user_id}")


class CreateAccountGroupModal(discord.ui.Modal):
    """Modal for creating a new account group."""

    name = discord.ui.TextInput(
        label="Account Group Name",
        placeholder="e.g., Main Wallet, Bank Account, Food",
        min_length=1,
        max_length=50,
    )

    description = discord.ui.TextInput(
        label="Description (optional)",
        placeholder="Brief description of this account",
        required=False,
        max_length=200,
    )

    account_type = discord.ui.TextInput(
        label="Account Type",
        placeholder="asset, liability, equity, revenue, or expense",
        min_length=4,
        max_length=10,
    )

    def __init__(
        self,
        alias: Optional[str] = None,
        repository: Optional[LedgerRepository] = None,
        user_id: Optional[str] = None,
    ):
        super().__init__(title="Create Account Group")
        self.alias = alias
        self.repository = repository
        self.user_id = user_id

        # Pre-fill the name with the alias if provided
        if alias:
            self.name.default = alias.title()

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Parse account type
            type_str = self.account_type.value.lower().strip()
            try:
                acc_type = AccountType(type_str)
            except ValueError:
                await interaction.response.send_message(
                    f"❌ Invalid account type '{type_str}'.\n"
                    f"Valid types: asset, liability, equity, revenue, expense",
                    ephemeral=True,
                )
                return

            # Get repository from cog if not set
            if not self.repository:
                from yuuka.db import get_repository

                self.repository = get_repository()

            user_id = self.user_id or str(interaction.user.id)

            # Create the account group
            group = self.repository.create_account_group(
                name=self.name.value.strip(),
                user_id=user_id,
                account_type=acc_type,
                description=self.description.value.strip()
                if self.description.value
                else None,
            )

            response = (
                f"✅ Account group created!\n\n"
                f"**{group.name}** ({format_account_type(group.account_type)})"
            )

            # If there was an alias, create the mapping
            if self.alias and group.id is not None:
                self.repository.add_account_alias(
                    alias=self.alias,
                    group_id=group.id,
                    user_id=user_id,
                )
                response += f"\n\n**'{self.alias}'** is now mapped to this group."

            await interaction.response.send_message(response, ephemeral=True)
            logger.info(f"User {user_id} created account group '{group.name}'")

        except ValueError as e:
            await interaction.response.send_message(
                f"❌ {str(e)}",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Error creating account group: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while creating the account group.",
                ephemeral=True,
            )


class NewAccountView(discord.ui.View):
    """
    View shown when a new account name is detected during transaction parsing.

    Allows user to assign the new name to an existing group or create a new one.
    """

    def __init__(
        self,
        account_name: str,
        repository: LedgerRepository,
        user_id: str,
        inferred_type: AccountType,
        on_complete: Optional[Callable] = None,
    ):
        super().__init__(timeout=120.0)
        self.account_name = account_name
        self.repository = repository
        self.user_id = user_id
        self.inferred_type = inferred_type
        self.on_complete = on_complete
        self.resolved_group: Optional[AccountGroup] = None

    @discord.ui.button(label="Assign to Existing", style=discord.ButtonStyle.primary)
    async def assign_existing(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Show dropdown to assign to existing account group."""
        groups = self.repository.get_user_account_groups(self.user_id)

        if not groups:
            await interaction.response.send_message(
                "📭 No account groups found. Please create one first using "
                "`/create_account`.",
                ephemeral=True,
            )
            return

        view = AccountGroupSelectView(
            groups=groups,
            alias=self.account_name,
            repository=self.repository,
            user_id=self.user_id,
        )

        await interaction.response.edit_message(
            content=(
                f"🔗 **Assign '{self.account_name}' to an account group**\n\n"
                f"Select an existing account group, or create a new one:"
            ),
            view=view,
        )

    @discord.ui.button(label="Create New Group", style=discord.ButtonStyle.success)
    async def create_new(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Show modal to create new account group."""
        modal = CreateAccountGroupModal(
            alias=self.account_name,
            repository=self.repository,
            user_id=self.user_id,
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Use as Standalone", style=discord.ButtonStyle.secondary)
    async def use_standalone(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Create a new group with this name and auto-assign."""
        try:
            # Create a group with the account name
            group = self.repository.create_account_group(
                name=self.account_name.title(),
                user_id=self.user_id,
                account_type=self.inferred_type,
                description=f"Auto-created from '{self.account_name}'",
            )

            self.resolved_group = group

            if group.id is None:
                await interaction.response.edit_message(
                    content="❌ Failed to create account group.",
                    view=None,
                )
                return

            await interaction.response.edit_message(
                content=(
                    f"✅ Created new account group!\n\n"
                    f"**{group.name}** ({format_account_type(group.account_type)})\n\n"
                    f"Future uses of '{self.account_name}' will map to this group."
                ),
                view=None,
            )

            if self.on_complete:
                await self.on_complete(group)

        except ValueError as e:
            await interaction.response.edit_message(
                content=f"❌ {str(e)}",
                view=None,
            )
        except Exception as e:
            logger.error(f"Error creating standalone group: {e}", exc_info=True)
            await interaction.response.edit_message(
                content="❌ An error occurred.",
                view=None,
            )

    async def on_timeout(self):
        logger.info(
            f"New account assignment timed out for '{self.account_name}' "
            f"(user {self.user_id})"
        )


class AccountsCog(commands.Cog):
    """Cog for account group and alias management."""

    def __init__(self, bot: commands.Bot, repository: LedgerRepository):
        self.bot = bot
        self.repository = repository

    @app_commands.command(
        name="create_account", description="Create a new account group"
    )
    @app_commands.describe(
        name="Name for the account group (e.g., 'Main Wallet', 'Food Expenses')",
        account_type="Type of account",
        description="Optional description for the account",
    )
    @app_commands.choices(
        account_type=[
            app_commands.Choice(name="💰 Asset (money you have)", value="asset"),
            app_commands.Choice(name="📋 Liability (money you owe)", value="liability"),
            app_commands.Choice(name="🏦 Equity (net worth)", value="equity"),
            app_commands.Choice(name="📈 Revenue (money coming in)", value="revenue"),
            app_commands.Choice(name="📉 Expense (money going out)", value="expense"),
        ]
    )
    async def create_account_command(
        self,
        interaction: discord.Interaction,
        name: str,
        account_type: str,
        description: Optional[str] = None,
    ):
        """Create a new account group."""
        try:
            user_id = str(interaction.user.id)
            acc_type = AccountType(account_type)

            group = self.repository.create_account_group(
                name=name.strip(),
                user_id=user_id,
                account_type=acc_type,
                description=description,
            )

            await interaction.response.send_message(
                f"✅ Account group created!\n\n"
                f"**{group.name}** ({format_account_type(group.account_type)})\n"
                f"{group.description or ''}\n\n"
                f"You can now add aliases using `/add_alias`.",
                ephemeral=True,
            )
            logger.info(f"User {user_id} created account group '{group.name}'")

        except ValueError as e:
            await interaction.response.send_message(
                f"❌ {str(e)}",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Error in create_account_command: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while creating the account group.",
                ephemeral=True,
            )

    @app_commands.command(
        name="add_alias", description="Add an alias to an account group"
    )
    @app_commands.describe(
        alias="The alias/alternate name (e.g., 'main pocket', 'jago main')",
        account_name="The account group to map this alias to",
    )
    async def add_alias_command(
        self,
        interaction: discord.Interaction,
        alias: str,
        account_name: str,
    ):
        """Add an alias to an existing account group."""
        try:
            user_id = str(interaction.user.id)

            # Find the account group
            group = self.repository.get_account_group_by_name(account_name, user_id)
            if not group:
                # Try to find by case-insensitive search
                groups = self.repository.get_user_account_groups(user_id)
                group = next(
                    (g for g in groups if g.name.lower() == account_name.lower()),
                    None,
                )

            if not group:
                await interaction.response.send_message(
                    f"❌ Account group '{account_name}' not found.\n"
                    f"Use `/account_groups` to see your account groups.",
                    ephemeral=True,
                )
                return

            # Add the alias
            if group.id is None:
                await interaction.response.send_message(
                    "❌ Invalid account group.",
                    ephemeral=True,
                )
                return

            account_alias = self.repository.add_account_alias(
                alias=alias.strip(),
                group_id=group.id,
                user_id=user_id,
            )

            await interaction.response.send_message(
                f"✅ Alias added!\n\n"
                f"**'{account_alias.alias}'** → **{group.name}**\n\n"
                f"Now when you use '{alias}' in transactions, "
                f"it will be recorded under '{group.name}'.",
                ephemeral=True,
            )
            logger.info(f"User {user_id} added alias '{alias}' to group '{group.name}'")

        except ValueError as e:
            await interaction.response.send_message(
                f"❌ {str(e)}",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Error in add_alias_command: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while adding the alias.",
                ephemeral=True,
            )

    @app_commands.command(
        name="remove_alias", description="Remove an alias from an account group"
    )
    @app_commands.describe(
        alias="The alias to remove",
    )
    async def remove_alias_command(
        self,
        interaction: discord.Interaction,
        alias: str,
    ):
        """Remove an alias."""
        try:
            user_id = str(interaction.user.id)

            # First check what group this alias maps to
            group = self.repository.resolve_account_alias(alias.strip(), user_id)

            removed = self.repository.remove_account_alias(alias.strip(), user_id)

            if removed:
                group_info = f" (was mapped to '{group.name}')" if group else ""
                await interaction.response.send_message(
                    f"✅ Alias '{alias}' removed{group_info}.",
                    ephemeral=True,
                )
                logger.info(f"User {user_id} removed alias '{alias}'")
            else:
                await interaction.response.send_message(
                    f"❌ Alias '{alias}' not found.",
                    ephemeral=True,
                )

        except Exception as e:
            logger.error(f"Error in remove_alias_command: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while removing the alias.",
                ephemeral=True,
            )

    @app_commands.command(
        name="account_groups", description="View your account groups and their aliases"
    )
    async def account_groups_command(self, interaction: discord.Interaction):
        """Show all account groups and their aliases."""
        try:
            user_id = str(interaction.user.id)
            groups = self.repository.get_user_account_groups(user_id)

            if not groups:
                await interaction.response.send_message(
                    "📭 No account groups found.\n\n"
                    "Create one with `/create_account` or record a transaction "
                    "to get started!",
                    ephemeral=True,
                )
                return

            # Group by account type
            by_type: dict[AccountType, list[AccountGroup]] = {
                t: [] for t in AccountType
            }
            for group in groups:
                by_type[group.account_type].append(group)

            lines = ["📋 **Your Account Groups**\n"]

            type_order = [
                AccountType.ASSET,
                AccountType.LIABILITY,
                AccountType.EQUITY,
                AccountType.REVENUE,
                AccountType.EXPENSE,
            ]

            for acc_type in type_order:
                type_groups = by_type[acc_type]
                if type_groups:
                    lines.append(f"**{format_account_type(acc_type)}**")

                    for group in type_groups:
                        system_marker = " ⚙️" if group.is_system else ""
                        lines.append(f"  **{group.name}**{system_marker}")

                        # Get aliases for this group
                        if group.id is not None:
                            aliases = self.repository.get_aliases_for_group(
                                group.id, user_id
                            )
                        else:
                            aliases = []
                        if aliases:
                            alias_str = ", ".join(f"`{a.alias}`" for a in aliases[:5])
                            if len(aliases) > 5:
                                alias_str += f" +{len(aliases) - 5} more"
                            lines.append(f"    ↳ Aliases: {alias_str}")

                    lines.append("")

            # Check for pending (unmapped) account names
            pending = self.repository.get_pending_account_names(user_id)
            if pending:
                lines.append("⚠️ **Unmapped Account Names**")
                lines.append("These names are used but not assigned to any group:")
                for name in pending[:10]:
                    lines.append(f"  • `{name}`")
                if len(pending) > 10:
                    lines.append(f"  ... and {len(pending) - 10} more")
                lines.append("")
                lines.append("Use `/assign_account` to map them to groups.")

            message = "\n".join(lines)
            if len(message) > 2000:
                message = message[:1997] + "..."

            await interaction.response.send_message(message, ephemeral=True)
            logger.info(f"Showed {len(groups)} account groups for user {user_id}")

        except Exception as e:
            logger.error(f"Error in accounts_command: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while retrieving your accounts.",
                ephemeral=True,
            )

    @app_commands.command(
        name="assign_account", description="Assign an unmapped account name to a group"
    )
    @app_commands.describe(
        account_name="The account name to assign (from your transactions)",
    )
    async def assign_account_command(
        self,
        interaction: discord.Interaction,
        account_name: str,
    ):
        """Assign an unmapped account name to an account group."""
        try:
            user_id = str(interaction.user.id)

            # Check if already mapped
            existing = self.repository.resolve_account_alias(account_name, user_id)
            if existing:
                await interaction.response.send_message(
                    f"ℹ️ '{account_name}' is already mapped to **{existing.name}**.",
                    ephemeral=True,
                )
                return

            # Get available groups
            groups = self.repository.get_user_account_groups(user_id)

            if not groups:
                await interaction.response.send_message(
                    "📭 No account groups found. Please create one first using "
                    "`/create_account`.",
                    ephemeral=True,
                )
                return

            # Infer account type
            inferred_type = self.repository.infer_account_type(account_name)

            view = NewAccountView(
                account_name=account_name.strip().lower(),
                repository=self.repository,
                user_id=user_id,
                inferred_type=inferred_type,
            )

            await interaction.response.send_message(
                f"🔗 **Assign '{account_name}' to an account group**\n\n"
                f"Inferred type: {format_account_type(inferred_type)}\n\n"
                f"Choose how to handle this account name:",
                view=view,
                ephemeral=True,
            )

        except Exception as e:
            logger.error(f"Error in assign_account_command: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred.",
                ephemeral=True,
            )

    @app_commands.command(
        name="lookup_account", description="Check which group an account name maps to"
    )
    @app_commands.describe(
        account_name="The account name to look up",
    )
    async def lookup_account_command(
        self,
        interaction: discord.Interaction,
        account_name: str,
    ):
        """Look up which group an account name maps to."""
        try:
            user_id = str(interaction.user.id)

            group = self.repository.resolve_account_alias(account_name.strip(), user_id)

            if group:
                # Get all aliases for this group
                if group.id is not None:
                    aliases = self.repository.get_aliases_for_group(group.id, user_id)
                    alias_list = ", ".join(f"`{a.alias}`" for a in aliases)
                else:
                    alias_list = "None"

                await interaction.response.send_message(
                    f"🔍 **'{account_name}'** → **{group.name}**\n\n"
                    f"Type: {format_account_type(group.account_type)}\n"
                    f"Description: {group.description or 'None'}\n"
                    f"All aliases: {alias_list}",
                    ephemeral=True,
                )
            else:
                inferred_type = self.repository.infer_account_type(account_name)
                await interaction.response.send_message(
                    f"❓ **'{account_name}'** is not mapped to any account group.\n\n"
                    f"Inferred type: {format_account_type(inferred_type)}\n\n"
                    f"Use `/assign_account {account_name}` to map it.",
                    ephemeral=True,
                )

        except Exception as e:
            logger.error(f"Error in lookup_account_command: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    """Setup function for loading the cog."""
    pass
