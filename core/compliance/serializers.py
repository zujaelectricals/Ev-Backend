from rest_framework import serializers
from .models import ComplianceDocument, TDSRecord


class ComplianceDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplianceDocument
        fields = '__all__'
        read_only_fields = ('user', 'uploaded_at', 'verified_at', 'verified_by', 'is_verified')


class TDSRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = TDSRecord
        fields = '__all__'
        read_only_fields = ('user', 'created_at')

