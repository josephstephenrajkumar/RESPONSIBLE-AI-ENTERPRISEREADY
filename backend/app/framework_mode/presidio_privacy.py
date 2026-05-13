import os
import re
from functools import lru_cache
from pathlib import Path

_TLD_CACHE_DIR = Path(__file__).resolve().parents[1] / 'storage' / 'tldextract_cache'
_TLD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('TLDEXTRACT_CACHE', str(_TLD_CACHE_DIR))

try:
    import tldextract
    import tldextract.tldextract as _tldextract_module

    _tldextract_module.TLD_EXTRACTOR = tldextract.TLDExtract(
        cache_dir=str(_TLD_CACHE_DIR),
        suffix_list_urls=()
    )
except ImportError:
    tldextract = None

try:
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerResult
    from presidio_anonymizer import AnonymizerEngine
    from presidio_anonymizer.entities import OperatorConfig

    _presidio_available = True
except ImportError:
    AnalyzerEngine = None
    Pattern = None
    PatternRecognizer = None
    RecognizerResult = None
    AnonymizerEngine = None
    OperatorConfig = None
    _presidio_available = False


_DEFAULT_ENTITIES = [
    'CREDIT_CARD',
    'CRYPTO',
    'EMAIL_ADDRESS',
    'IBAN_CODE',
    'IP_ADDRESS',
    'LOCATION',
    'NRP',
    'PERSON',
    'PHONE_NUMBER',
    'US_BANK_NUMBER',
    'US_DRIVER_LICENSE',
    'US_ITIN',
    'US_PASSPORT',
    'US_SSN',
]

_FALLBACK_PATTERNS = [
    ('EMAIL_ADDRESS', re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')),
    ('PHONE_NUMBER', re.compile(r'(?<!\d)(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?!\d)')),
    ('US_SSN', re.compile(r'\b\d{3}-\d{2}-\d{4}\b')),
    ('CREDIT_CARD', re.compile(r'\b(?:\d[ -]*?){13,19}\b')),
    ('IP_ADDRESS', re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')),
    ('API_KEY', re.compile(r'\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*[^\s,;]+', re.IGNORECASE)),
    ('PASSWORD_DISCLOSURE', re.compile(r'\b(?:my\s+)?password\s+(?:is|=|:)\s*[^\s,;]+', re.IGNORECASE)),
    ('SG_NRIC_FIN', re.compile(r'\b[STFGM]\d{7}[A-Z]\b', re.IGNORECASE)),
]


def _add_custom_recognizers(analyzer):
    registry = analyzer.registry
    registry.add_recognizer(
        PatternRecognizer(
            supported_entity='API_KEY',
            name='API key and secret recognizer',
            patterns=[
                Pattern(
                    name='key-value secret',
                    regex=r'\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*[^\s,;]+',
                    score=0.85
                )
            ],
            supported_language='en'
        )
    )
    registry.add_recognizer(
        PatternRecognizer(
            supported_entity='SG_NRIC_FIN',
            name='Singapore NRIC/FIN recognizer',
            patterns=[
                Pattern(
                    name='sg nric fin',
                    regex=r'\b[STFGM]\d{7}[A-Z]\b',
                    score=0.75
                )
            ],
            supported_language='en',
            context=['nric', 'fin', 'singapore', 'identity', 'id']
        )
    )


@lru_cache(maxsize=1)
def _get_presidio_engines():
    if not _presidio_available:
        return None, None, 'Presidio packages are not installed'

    try:
        analyzer = AnalyzerEngine()
        _add_custom_recognizers(analyzer)
        anonymizer = AnonymizerEngine()
        return analyzer, anonymizer, None
    except Exception as exc:
        return None, None, str(exc)


def _dedupe_findings(findings):
    seen = set()
    deduped = []
    for finding in sorted(findings, key=lambda item: (item['start'], item['end'], item['entity_type'])):
        key = (finding['entity_type'], finding['start'], finding['end'])
        if key not in seen:
            seen.add(key)
            deduped.append(finding)
    return deduped


def _remove_contained_findings(findings):
    filtered = []
    for finding in findings:
        contained_by_stronger_finding = any(
            other is not finding
            and other['start'] <= finding['start']
            and other['end'] >= finding['end']
            and other['score'] >= finding['score']
            for other in findings
        )
        if not contained_by_stronger_finding:
            filtered.append(finding)
    return filtered


def _risk_for(findings):
    if any(item['entity_type'] in {'CREDIT_CARD', 'US_SSN', 'US_PASSPORT', 'API_KEY', 'PASSWORD_DISCLOSURE'} for item in findings):
        return 'high'
    if findings:
        return 'medium'
    return 'low'


def _fallback_analyze_and_redact(message):
    findings = _fallback_findings(message)
    redacted = _redact_with_findings(message, findings)
    return findings, redacted


def _fallback_findings(message):
    findings = []
    for entity_type, pattern in _FALLBACK_PATTERNS:
        for match in pattern.finditer(message):
            findings.append({
                'entity_type': entity_type,
                'start': match.start(),
                'end': match.end(),
                'score': 0.65,
                'source': 'regex_fallback'
            })

    return _remove_contained_findings(_dedupe_findings(findings))


def _redact_with_findings(message, findings):
    redacted = message
    for finding in sorted(findings, key=lambda item: item['start'], reverse=True):
        redacted = (
            redacted[:finding['start']]
            + f"<{finding['entity_type']}>"
            + redacted[finding['end']:]
        )
    return redacted


def _presidio_analyze_and_redact(message, analyzer, anonymizer):
    results = analyzer.analyze(
        text=message,
        entities=_DEFAULT_ENTITIES + ['API_KEY', 'SG_NRIC_FIN'],
        language='en'
    )
    fallback_findings = _fallback_findings(message)
    for finding in fallback_findings:
        overlaps_existing = any(
            not (finding['end'] <= result.start or finding['start'] >= result.end)
            and result.score >= finding['score']
            for result in results
        )
        if not overlaps_existing:
            results.append(
                RecognizerResult(
                    entity_type=finding['entity_type'],
                    start=finding['start'],
                    end=finding['end'],
                    score=finding['score']
                )
            )

    results = [
        RecognizerResult(
            entity_type=finding['entity_type'],
            start=finding['start'],
            end=finding['end'],
            score=finding['score']
        )
        for finding in _remove_contained_findings(_dedupe_findings([
            {
                'entity_type': result.entity_type,
                'start': result.start,
                'end': result.end,
                'score': round(float(result.score), 3),
                'source': 'presidio'
            }
            for result in results
        ]))
    ]
    anonymized = anonymizer.anonymize(
        text=message,
        analyzer_results=results,
        operators={
            'DEFAULT': OperatorConfig('replace', {'new_value': '<PII>'}),
            'API_KEY': OperatorConfig('replace', {'new_value': '<API_KEY>'}),
            'CREDIT_CARD': OperatorConfig('replace', {'new_value': '<CREDIT_CARD>'}),
            'EMAIL_ADDRESS': OperatorConfig('replace', {'new_value': '<EMAIL_ADDRESS>'}),
            'PHONE_NUMBER': OperatorConfig('replace', {'new_value': '<PHONE_NUMBER>'}),
            'PASSWORD_DISCLOSURE': OperatorConfig('replace', {'new_value': '<PASSWORD>'}),
            'SG_NRIC_FIN': OperatorConfig('replace', {'new_value': '<SG_NRIC_FIN>'}),
            'US_SSN': OperatorConfig('replace', {'new_value': '<US_SSN>'}),
        }
    )
    findings = _remove_contained_findings(_dedupe_findings([
        {
            'entity_type': result.entity_type,
            'start': result.start,
            'end': result.end,
            'score': round(float(result.score), 3),
            'source': 'presidio'
        }
        for result in results
    ]))
    return findings, anonymized.text


def evaluate_privacy(message):
    message = message or ''
    analyzer, anonymizer, setup_error = _get_presidio_engines()

    if analyzer and anonymizer:
        findings, redacted_text = _presidio_analyze_and_redact(message, analyzer, anonymizer)
        engine = 'presidio'
        recommendation = (
            'Sensitive data was redacted before model processing'
            if findings
            else 'No sensitive data detected by Presidio'
        )
    else:
        findings, redacted_text = _fallback_analyze_and_redact(message)
        engine = 'regex_fallback'
        recommendation = (
            'Install presidio-analyzer, presidio-anonymizer, and a spaCy English model for full local PII detection'
            if setup_error
            else 'No sensitive data detected'
        )

    detected_entities = sorted({item['entity_type'] for item in findings})
    return {
        'privacy_engine': engine,
        'privacy_risk': _risk_for(findings),
        'detected_sensitive_terms': detected_entities,
        'detected_entities': detected_entities,
        'findings_count': len(findings),
        'findings': findings,
        'redacted': bool(findings),
        'redacted_text': redacted_text,
        'setup_error': setup_error,
        'recommendation': recommendation
    }
