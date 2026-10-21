"""Add collaboration tables without altering existing user/task/message tables."""
from alembic import op
import sqlalchemy as sa

revision = "assistant_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    def create(name, *columns):
        if name not in existing:
            op.create_table(name, *columns)
    def session_id(primary=False):
        return sa.Column("session_id", sa.Integer(), sa.ForeignKey("assistant_sessions.id", ondelete="CASCADE"), primary_key=primary, nullable=False)
    def user_id(primary=False):
        return sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=primary, nullable=False)
    def created():
        return sa.Column("created_at", sa.DateTime(), nullable=False)
    create("assistant_members", session_id(True), user_id(True),
           sa.Column("invited_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), created())
    create("assistant_expert_profiles", user_id(True), sa.Column("specialty", sa.String(128), nullable=False),
           sa.Column("bio", sa.Text(), nullable=False), sa.Column("tags", sa.JSON(), nullable=False))
    create("assistant_runs", sa.Column("id", sa.String(36), primary_key=True), session_id(), user_id(),
           sa.Column("client_message_id", sa.String(64), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
           sa.Column("active_session_id", sa.Integer(), unique=True), sa.Column("status", sa.String(16), nullable=False),
           created(), sa.Column("expires_at", sa.DateTime(), nullable=False),
           sa.UniqueConstraint("session_id", "user_id", "client_message_id"))
    create("assistant_message_authors", sa.Column("message_id", sa.Integer(), sa.ForeignKey("assistant_messages.id", ondelete="CASCADE"), primary_key=True),
           sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")), sa.Column("display_name", sa.String(128), nullable=False), sa.Column("run_id", sa.String(36)))
    create("assistant_events", sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), session_id(),
           sa.Column("run_id", sa.String(36)), sa.Column("payload", sa.JSON(), nullable=False), created())
    create("assistant_audit", sa.Column("id", sa.Integer(), primary_key=True), session_id(),
           sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
           sa.Column("action", sa.String(32), nullable=False), sa.Column("subject_id", sa.Integer()), created())
    create("assistant_user_skills", user_id(True), sa.Column("skill_id", sa.String(64), primary_key=True),
           sa.Column("version", sa.String(64), nullable=False), sa.Column("content_hash", sa.String(64), nullable=False), created())
    for table in ("assistant_runs", "assistant_events", "assistant_audit"):
        names = {index['name'] for index in sa.inspect(op.get_bind()).get_indexes(table)}
        name = f"ix_{table}_session_id"
        if name not in names:
            op.create_index(name, table, ["session_id"])


def downgrade():
    # Downgrade intentionally is not a data-deletion shortcut for live discussions.
    raise RuntimeError("回退应用代码可保留新增表；若需删除协作历史，请先备份并由部署负责人显式处置。")
