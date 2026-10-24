"""Store personal instruction-only OpenCode skills per reviewer."""
from alembic import op
import sqlalchemy as sa

revision = "assistant_002"
down_revision = "assistant_001"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "assistant_custom_skills" not in set(inspector.get_table_names()):
        op.create_table(
            "assistant_custom_skills",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("document", sa.Text(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("assistant_custom_skills")}
    if "ix_assistant_custom_skills_user_id" not in indexes:
        op.create_index("ix_assistant_custom_skills_user_id", "assistant_custom_skills", ["user_id"])


def downgrade():
    raise RuntimeError("个人技能含用户内容；回退代码可保留数据，如需删除必须经数据所有者确认并先备份。")
