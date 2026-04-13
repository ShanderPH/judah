"""
Fake initial migration for knowledge app.
Tables kb_articles, kb_categories, kb_article_chunks, kb_sync_logs
already exist in HelpdeskDB.
Run with: python manage.py migrate knowledge --fake-initial
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("hubspot_id", models.CharField(db_index=True, max_length=255, unique=True)),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True, null=True)),
                ("full_path", models.CharField(blank=True, max_length=500, null=True)),
                ("icon_name", models.CharField(blank=True, max_length=100, null=True)),
                ("color", models.CharField(blank=True, max_length=50, null=True)),
                ("position", models.IntegerField(default=0)),
                ("article_count", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
            ],
            options={
                "db_table": "kb_categories",
                "ordering": ["position", "name"],
                "verbose_name_plural": "categories",
            },
        ),
        migrations.CreateModel(
            name="Article",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("hubspot_id", models.CharField(db_index=True, max_length=255, unique=True)),
                ("title", models.CharField(max_length=500)),
                ("slug", models.CharField(blank=True, db_index=True, max_length=500, null=True)),
                ("path", models.CharField(blank=True, max_length=500, null=True)),
                ("body_html", models.TextField(blank=True, null=True)),
                ("body_plain", models.TextField(blank=True, null=True)),
                ("summary", models.TextField(blank=True, null=True)),
                ("meta_description", models.TextField(blank=True, null=True)),
                ("absolute_url", models.CharField(blank=True, max_length=500, null=True)),
                ("canonical_url", models.CharField(blank=True, max_length=500, null=True)),
                ("category_hubspot_id", models.CharField(blank=True, db_index=True, max_length=255, null=True)),
                ("category_name", models.CharField(blank=True, max_length=255, null=True)),
                ("category_icon", models.CharField(blank=True, max_length=100, null=True)),
                ("category_color", models.CharField(blank=True, max_length=50, null=True)),
                ("tags", models.JSONField(blank=True, default=list)),
                ("tag_ids", models.JSONField(blank=True, default=list)),
                ("language", models.CharField(default="pt-br", max_length=10)),
                ("state", models.CharField(db_index=True, default="PUBLISHED", max_length=50)),
                ("position", models.IntegerField(default=0)),
                ("view_count", models.IntegerField(default=0)),
                ("rating_sum", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("rating_count", models.IntegerField(default=0)),
                ("content_hash", models.CharField(blank=True, max_length=100, null=True)),
                ("hs_created_at", models.DateTimeField(blank=True, null=True)),
                ("hs_updated_at", models.DateTimeField(blank=True, null=True)),
                ("hs_published_at", models.DateTimeField(blank=True, null=True)),
                ("synced_at", models.DateTimeField(auto_now=True, null=True)),
                ("estimated_read_time", models.IntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
            ],
            options={"db_table": "kb_articles", "ordering": ["-updated_at"]},
        ),
        migrations.CreateModel(
            name="ArticleChunk",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "article",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunks",
                        to="knowledge.article",
                    ),
                ),
                ("article_hubspot_id", models.CharField(db_index=True, max_length=255)),
                ("pinecone_id", models.CharField(db_index=True, max_length=255, unique=True)),
                ("chunk_index", models.IntegerField()),
                ("chunk_text", models.TextField()),
                ("chunk_type", models.CharField(default="paragraph", max_length=50, null=True)),
                ("token_count", models.IntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
            ],
            options={"db_table": "kb_article_chunks", "ordering": ["article", "chunk_index"]},
        ),
        migrations.CreateModel(
            name="KBSyncLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("sync_type", models.CharField(max_length=50)),
                ("started_at", models.DateTimeField(auto_now_add=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("total_articles", models.IntegerField(default=0)),
                ("articles_created", models.IntegerField(default=0)),
                ("articles_updated", models.IntegerField(default=0)),
                ("articles_unchanged", models.IntegerField(default=0)),
                ("chunks_created", models.IntegerField(default=0)),
                ("status", models.CharField(default="running", max_length=20)),
                ("error_message", models.TextField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
            ],
            options={"db_table": "kb_sync_logs", "ordering": ["-started_at"]},
        ),
        migrations.AlterUniqueTogether(
            name="articlechunk",
            unique_together={("article", "chunk_index")},
        ),
        migrations.AddIndex(
            model_name="article",
            index=models.Index(fields=["state", "category_hubspot_id"], name="kb_articles_state_cat_idx"),
        ),
    ]
