"""Models for knowledge base domain — mapped to existing HelpdeskDB kb_* tables."""

import uuid

from django.db import models


class Category(models.Model):
    """KB category — maps to existing kb_categories table."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hubspot_id = models.CharField(max_length=255, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    full_path = models.CharField(max_length=500, blank=True, null=True)
    icon_name = models.CharField(max_length=100, blank=True, null=True)
    color = models.CharField(max_length=50, blank=True, null=True)
    position = models.IntegerField(default=0)
    article_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        db_table = "kb_categories"
        ordering = ["position", "name"]
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name


class Article(models.Model):
    """KB article — maps to existing kb_articles table."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hubspot_id = models.CharField(max_length=255, unique=True, db_index=True)
    title = models.CharField(max_length=500)
    slug = models.CharField(max_length=500, blank=True, null=True, db_index=True)
    path = models.CharField(max_length=500, blank=True, null=True)
    body_html = models.TextField(blank=True, null=True)
    body_plain = models.TextField(blank=True, null=True)
    summary = models.TextField(blank=True, null=True)
    meta_description = models.TextField(blank=True, null=True)
    absolute_url = models.CharField(max_length=500, blank=True, null=True)
    canonical_url = models.CharField(max_length=500, blank=True, null=True)
    category_hubspot_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    category_name = models.CharField(max_length=255, blank=True, null=True)
    category_icon = models.CharField(max_length=100, blank=True, null=True)
    category_color = models.CharField(max_length=50, blank=True, null=True)
    tags = models.JSONField(default=list, blank=True)
    tag_ids = models.JSONField(default=list, blank=True)
    language = models.CharField(max_length=10, default="pt-br")
    state = models.CharField(max_length=50, default="PUBLISHED", db_index=True)
    position = models.IntegerField(default=0)
    view_count = models.IntegerField(default=0)
    rating_sum = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rating_count = models.IntegerField(default=0)
    content_hash = models.CharField(max_length=100, blank=True, null=True)
    hs_created_at = models.DateTimeField(null=True, blank=True)
    hs_updated_at = models.DateTimeField(null=True, blank=True)
    hs_published_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True, null=True)
    estimated_read_time = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        db_table = "kb_articles"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["state", "category_hubspot_id"]),
        ]

    def __str__(self) -> str:
        return self.title


class ArticleChunk(models.Model):
    """KB article chunk for RAG — maps to existing kb_article_chunks table."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="chunks", null=True, blank=True)
    article_hubspot_id = models.CharField(max_length=255, db_index=True)
    pinecone_id = models.CharField(max_length=255, unique=True, db_index=True)
    chunk_index = models.IntegerField()
    chunk_text = models.TextField()
    chunk_type = models.CharField(max_length=50, default="paragraph", null=True)
    token_count = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        db_table = "kb_article_chunks"
        ordering = ["article", "chunk_index"]
        unique_together = [("article", "chunk_index")]

    def __str__(self) -> str:
        return f"{self.article_hubspot_id} — chunk {self.chunk_index}"


class KBSyncLog(models.Model):
    """Sync log for HubSpot KB synchronisation — maps to kb_sync_logs table."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sync_type = models.CharField(max_length=50)
    started_at = models.DateTimeField(auto_now_add=True, null=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    total_articles = models.IntegerField(default=0)
    articles_created = models.IntegerField(default=0)
    articles_updated = models.IntegerField(default=0)
    articles_unchanged = models.IntegerField(default=0)
    chunks_created = models.IntegerField(default=0)
    status = models.CharField(max_length=20, default="running")
    error_message = models.TextField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "kb_sync_logs"
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.sync_type} [{self.status}] @ {self.started_at}"
