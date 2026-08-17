from django.contrib import admin

from .models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "step", "progress", "created_at", "output_name")
    list_filter = ("status", "step")
    readonly_fields = ("id", "created_at", "updated_at", "parse", "choices")
    ordering = ("-created_at",)

    def delete_queryset(self, request, queryset):
        # Go through Job.delete so each workspace directory is removed too.
        for job in queryset:
            job.delete()
