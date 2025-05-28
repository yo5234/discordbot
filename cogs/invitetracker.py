import discord
from discord.ext import commands
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

class InviteTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not firebase_admin._apps:
            creds_dict = json.loads(os.getenv("FIREBASE_CREDS"))
            cred = credentials.Certificate(creds_dict)
            firebase_admin.initialize_app(cred)
        self.db = firestore.client()

        self.invites = {}
        self.staff_role_id = 1377330050159874118
        self.reset_user_id = 984152481225404467

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            self.invites[guild.id] = await guild.invites()

    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        self.invites[invite.guild.id] = await invite.guild.invites()

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        self.invites[invite.guild.id] = await invite.guild.invites()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        before_invites = self.invites.get(guild.id, [])
        after_invites = await guild.invites()

        used_invite = None
        for invite in before_invites:
            for new_invite in after_invites:
                if invite.code == new_invite.code and invite.uses < new_invite.uses:
                    used_invite = new_invite
                    break
            if used_invite:
                break

        self.invites[guild.id] = after_invites

        if used_invite:
            inviter = guild.get_member(used_invite.inviter.id)
            if inviter and self.staff_role_id in [role.id for role in inviter.roles]:
                inviter_id = str(inviter.id)
                inviter_doc = self.db.collection("invites").document(inviter_id)
                inviter_data = inviter_doc.get().to_dict() or {"total": 0, "weekly": 0}
                inviter_data["total"] += 1
                inviter_data["weekly"] += 1
                inviter_doc.set(inviter_data)

                # Save which inviter invited this member
                self.db.collection("invited_members").document(str(member.id)).set({"inviter_id": inviter_id})

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        doc_ref = self.db.collection("invited_members").document(str(member.id))
        doc = doc_ref.get()
        if not doc.exists:
            return

        inviter_id = doc.to_dict().get("inviter_id")
        inviter_doc = self.db.collection("invites").document(inviter_id)
        inviter_data = inviter_doc.get().to_dict()
        if not inviter_data:
            return

        inviter_data["total"] = max(inviter_data.get("total", 1) - 1, 0)
        inviter_data["weekly"] = max(inviter_data.get("weekly", 1) - 1, 0)
        inviter_doc.set(inviter_data)

        doc_ref.delete()

    @commands.command(name="invites")
    async def check_invites(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        if self.staff_role_id not in [role.id for role in member.roles]:
            return await ctx.send("Only staff members have tracked invites.")

        doc = self.db.collection("invites").document(str(member.id)).get()
        data = doc.to_dict() or {"total": 0, "weekly": 0}
        embed = discord.Embed(
            title=f"{member.name}'s Invites",
            description=f"Total: {data['total']} | Weekly: {data['weekly']}",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)

    @commands.command(name="weeklyleaderboard")
    async def weekly_leaderboard(self, ctx):
        docs = self.db.collection("invites").stream()
        filtered = []
        for doc in docs:
            user_id = doc.id
            data = doc.to_dict()
            member = ctx.guild.get_member(int(user_id))
            if member and self.staff_role_id in [role.id for role in member.roles]:
                filtered.append((member, data.get("weekly", 0)))

        leaderboard = sorted(filtered, key=lambda x: x[1], reverse=True)
        embed = discord.Embed(
            title="Weekly Invite Leaderboard (Staff Only)",
            color=discord.Color.gold()
        )
        for i, (member, count) in enumerate(leaderboard[:10], start=1):
            embed.add_field(name=f"#{i} - {member.display_name}", value=f"{count} invites", inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="resetweekly")
    async def reset_weekly(self, ctx):
        if ctx.author.id != self.reset_user_id:
            return await ctx.send("You do not have permission to use this command.")

        docs = self.db.collection("invites").stream()
        for doc in docs:
            self.db.collection("invites").document(doc.id).update({"weekly": 0})
        await ctx.send("Weekly invite counts have been reset.")

async def setup(bot):
    await bot.add_cog(InviteTracker(bot))
