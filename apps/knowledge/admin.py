"""Django Admin configuration for knowledge base."""

from django.contrib import admin

from apps.knowledge.models import Article, ArticleChunk, Category, KBSyncLog


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "hubspot_id", "position", "article_count", "updated_at")
    search_fields = ("name", "hubspot_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "hubspot_id", "state", "category_name", "view_count", "synced_at")
    list_filter = ("state", "language")
    search_fields = ("title", "hubspot_id", "slug", "category_name")
    readonly_fields = ("view_count", "rating_sum", "rating_count", "synced_at", "created_at", "updated_at")


@admin.register(ArticleChunk)
class ArticleChunkAdmin(admin.ModelAdmin):
    list_display = ("article_hubspot_id", "chunk_index", "chunk_type", "token_count", "created_at")
    search_fields = ("article_hubspot_id", "chunk_text")
    readonly_fields = ("pinecone_id", "created_at")


@admin.register(KBSyncLog)
class KBSyncLogAdmin(admin.ModelAdmin):
    list_display = ("sync_type", "status", "total_articles", "articles_created", "articles_updated", "started_at")
    list_filter = ("status", "sync_type")
    readonly_fields = ("started_at",)
