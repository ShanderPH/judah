"""Models for knowledge base domain."""

from django.db import models


class Category(models.Model):
    """Hierarchical category for grouping knowledge base articles."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children")
    order = models.PositiveSmallIntegerField(default=0)
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "kb_categories"
        ordering = ["order", "name"]
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name


class Article(models.Model):
    """Knowledge base article with full-text and semantic search support."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    title = models.CharField(max_length=500)
    slug = models.SlugField(max_length=500, unique=True)
    content = models.TextField()
    summary = models.TextField(blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="articles")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    view_count = models.PositiveIntegerField(default=0)
    helpful_count = models.PositiveIntegerField(default=0)
    not_helpful_count = models.PositiveIntegerField(default=0)
    pinecone_id = models.CharField(max_length=100, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "kb_articles"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["status", "category"]),
        ]

    def __str__(self) -> str:
        return self.title


class ArticleChunk(models.Model):
    """Chunked segment of an article for RAG vector storage."""

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveSmallIntegerField()
    content = models.TextField()
    token_count = models.PositiveSmallIntegerField(default=0)
    pinecone_id = models.CharField(max_length=100, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "kb_article_chunks"
        ordering = ["article", "chunk_index"]
        unique_together = [("article", "chunk_index")]

    def __str__(self) -> str:
        return f"{self.article.title} — chunk {self.chunk_index}"
