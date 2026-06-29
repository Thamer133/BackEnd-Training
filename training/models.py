from django.db import models

class Person(models.Model):
    name = models.CharField(max_length=255)
    civil_id = models.CharField(max_length=12, unique=True)
    nationality = models.CharField(max_length=100)

    class Meta:
        db_table = 'training_person'

    def __str__(self):
        return self.name