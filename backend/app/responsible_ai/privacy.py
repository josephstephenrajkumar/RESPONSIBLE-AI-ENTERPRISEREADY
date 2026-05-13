def evaluate_privacy(message):
    private_keywords = ['password', 'ssn', 'credit card', 'secret', 'private']
    matches = [word for word in private_keywords if word in message.lower()]
    return {
        'privacy_risk': 'high' if matches else 'low',
        'detected_sensitive_terms': matches,
        'recommendation': 'Avoid sharing sensitive personal information'
    }
