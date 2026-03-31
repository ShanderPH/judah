"""Django Admin configuration for knowledge base."""

from django.contrib import admin

from apps.knowledge.models import Article, ArticleChunk, Category


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "parent", "order", "is_public")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "status", "view_count", "updated_at")
    list_filter = ("status", "category")
    search_fields = ("title", "content", "slug")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("view_count", "helpful_count", "not_helpful_count", "pinecone_id")


@admin.register(ArticleChunk)
class ArticleChunkAdmin(admin.ModelAdmin):
    list_display = ("article", "chunk_index", "token_count")
    search_fields = ("article__title",)
    readonly_fields = ("pinecone_id",)
