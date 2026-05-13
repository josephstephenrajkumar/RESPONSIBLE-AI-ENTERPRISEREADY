from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import Base, SafetyPolicy, SessionLocal, engine
from app.policy_governance import create_policy


SEED_POLICIES = [
    {
        'name': 'Violence or Harm Starter Policy',
        'category': 'violence_or_harm',
        'severity': 'high',
        'description': 'Imported from the legacy framework-mode starter rules.',
        'source': 'legacy_guardrails_safety.py',
        'patterns': [
            {'pattern': r'\bkill\b'},
            {'pattern': r'\bharm\b'},
            {'pattern': r'\bpoison\b'},
            {'pattern': r'\battack\b'},
            {'pattern': r'\bmake\s+(?:a\s+)?bomb\b'},
        ],
    },
    {
        'name': 'Cyber Abuse Starter Policy',
        'category': 'cyber_abuse',
        'severity': 'high',
        'description': 'Imported from the legacy framework-mode starter rules.',
        'source': 'legacy_guardrails_safety.py',
        'patterns': [
            {'pattern': r'\bexploit\b'},
            {'pattern': r'\bmalware\b'},
            {'pattern': r'\bransomware\b'},
            {'pattern': r'\bcredential\s*(?:theft|stealing|harvesting)\b'},
            {'pattern': r'\bbypass\s+(?:mfa|2fa|authentication|login)\b'},
        ],
    },
    {
        'name': 'Fraud or Phishing Starter Policy',
        'category': 'fraud_or_phishing',
        'severity': 'high',
        'description': 'Imported from the legacy framework-mode starter rules.',
        'source': 'legacy_guardrails_safety.py',
        'patterns': [
            {'pattern': r'\b(?:create|build|write|send|launch|run)\s+(?:a\s+)?phishing\b'},
            {'pattern': r'\bphishing\s+(?:kit|page|site|email|message|campaign|template)\b'},
            {'pattern': r'\bspoof(?:ing)?\s+(?:a\s+)?(?:bank|payment|login|website|email)\b'},
            {'pattern': r'\b(?:run|create|build)\s+(?:a\s+)?scam\b'},
            {'pattern': r'\bfake\s+(?:invoice|bank|payment|login|website)\b'},
            {'pattern': r'\bsteal\s+(?:money|credentials|passwords?|card|account)\b'},
        ],
    },
    {
        'name': 'Money Laundering Starter Policy',
        'category': 'money_laundering',
        'severity': 'high',
        'description': 'Imported from the legacy framework-mode starter rules.',
        'source': 'legacy_guardrails_safety.py',
        'patterns': [
            {'pattern': r'\bmoney\s+launder(?:ing)?\b'},
            {'pattern': r'\blayer(?:ing)?\s+transactions\b'},
            {'pattern': r'\bstructure\s+(?:cash\s+)?deposits\b'},
            {'pattern': r'\bavoid\s+(?:aml|kyc|sanctions|transaction\s+monitoring)\b'},
        ],
    },
    {
        'name': 'Unsafe Financial Action Starter Policy',
        'category': 'unsafe_financial_action',
        'severity': 'medium',
        'description': 'Imported from the legacy framework-mode starter rules.',
        'source': 'legacy_guardrails_safety.py',
        'patterns': [
            {'pattern': r'\bexecute\s+(?:a\s+)?(?:wire|transfer|payment|trade|transaction)\b'},
            {'pattern': r'\bapprove\s+(?:this\s+)?(?:loan|payment|wire|transaction)\b'},
            {'pattern': r'\bwithout\s+human\s+approval\b'},
        ],
    },
]


def main():
    Base.metadata.create_all(bind=engine)
    created = 0
    for policy in SEED_POLICIES:
        with SessionLocal() as session:
            exists = session.query(SafetyPolicy).filter_by(name=policy['name'], source=policy['source']).first()
        if exists:
            continue
        create_policy(policy, actor='seed-script')
        created += 1
    print(f'Seeded {created} draft safety policies.')


if __name__ == '__main__':
    main()
