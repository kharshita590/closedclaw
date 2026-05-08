from __future__ import annotations

import os
import sys
from pathlib import Path

import discord
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from channel_policy import ChannelPolicy, PairingStore  # noqa: E402
from enabled_channels import channel_enabled  # noqa: E402

AGENT_URL = os.getenv("AGENT_URL", "http://agent:8000").rstrip("/")
AGENT_API_KEY = os.getenv("AGENT_API_KEY") or os.getenv("AGENT_API_KEYS", "").split(",")[0].strip()
PAIRING_TTL = int(os.getenv("PAIRING_CODE_TTL_SECONDS", "600"))
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

policy = ChannelPolicy()
pairing = PairingStore(ttl_seconds=PAIRING_TTL)


def _agent_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {AGENT_API_KEY}"} if AGENT_API_KEY else {}


class ClosedClawDiscordBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)

        @self.tree.command(name="chat", description="Chat with your ClosedClaw agent")
        async def chat(interaction: discord.Interaction, message: str):
            if not channel_enabled("discord"):
                await interaction.response.send_message("Discord bridge is disabled (ENABLED_CHANNELS).", ephemeral=True)
                return
            sender_id = str(interaction.user.id)
            if not policy.is_allowed("discord", sender_id):
                text = message.strip()
                if text.isdigit() and len(text) == 6:
                    ok, reason = pairing.verify_code("discord", sender_id, text)
                    if ok:
                        policy.add_sender("discord", sender_id)
                        await interaction.response.send_message("Pairing complete. You can now message the agent.", ephemeral=True)
                        return
                    await interaction.response.send_message(f"Pairing failed: {reason}", ephemeral=True)
                    return
                code = pairing.create_code("discord", sender_id)
                await interaction.response.send_message(
                    f"Pairing required. Re-run `/chat` with this 6-digit code within 10 minutes: {code}",
                    ephemeral=True,
                )
                return

            await interaction.response.defer(thinking=True)
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{AGENT_URL}/chat",
                    headers=_agent_headers(),
                    json={
                        "message": message,
                        "channel": "discord",
                        "user_id": sender_id,
                        "thread_id": str(interaction.channel_id),
                        "group_id": str(interaction.guild_id) if interaction.guild_id else None,
                        "metadata": {"channel_id": interaction.channel_id, "guild_id": interaction.guild_id},
                    },
                )
                resp.raise_for_status()
                result = resp.json()
            await interaction.followup.send(result.get("response") or "Done.")

    async def setup_hook(self) -> None:
        await self.tree.sync()


def main() -> None:
    if not DISCORD_BOT_TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN is required")
    bot = ClosedClawDiscordBot()
    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()

