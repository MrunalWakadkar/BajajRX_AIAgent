from django.db import models



class Document(models.Model):
    name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500, blank=True, null=True)
    upload_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Clause(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='clauses')
    clause_text = models.TextField()
    keywords = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Query(models.Model):
    query_text = models.TextField()
    parsed_data = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Decision(models.Model):
    DECISION_CHOICES = (
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Needs Review', 'Needs Review')
    )
    query = models.ForeignKey(Query, on_delete=models.CASCADE, related_name='decisions')
    decision_status = models.CharField(max_length=20, choices=DECISION_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    justification = models.TextField()
    referenced_clauses = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
