from django.contrib import admin

from .models import Document, Clause, Query, Decision

admin.site.register(Document)
admin.site.register(Clause)
admin.site.register(Query)
admin.site.register(Decision)