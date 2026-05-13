import re


def _matched_terms(text, terms):
    content = text or ''
    return [
        term
        for term in terms
        if re.search(rf'\b{re.escape(term)}\b', content, re.IGNORECASE)
    ]


def evaluate_fairness(message, answer=None):
    protected_terms = ['race', 'gender', 'religion', 'orientation', 'age']
    biased_terms = ['superior', 'inferior', 'better than', 'worse than', 'supremacy', 'inferiority']

    message_flags = _matched_terms(message, protected_terms)

    # Analyze response for biased language if provided
    response_flags = []
    risk_level = 'low'

    if answer:
        answer_lower = answer.lower()
        # Check for biased terms, but exclude when they're used to reject bias
        for term in biased_terms:
            if term in answer_lower:
                # Check if the term is used in a rejecting context
                context_words = ['not', 'no', 'reject', 'debunk', 'disproven', 'harmful', 'outdated', 'false']
                term_index = answer_lower.find(term)
                # Look at surrounding context (100 chars before and after)
                start = max(0, term_index - 100)
                end = min(len(answer_lower), term_index + len(term) + 100)
                context = answer_lower[start:end]

                # If context contains rejection words, don't flag as biased
                if not any(reject_word in context for reject_word in context_words):
                    response_flags.append(term)

        if response_flags:
            risk_level = 'high'
        elif message_flags:
            risk_level = 'medium'
    else:
        if message_flags:
            risk_level = 'medium'

    return {
        'fairness_risk': risk_level,
        'protected_attributes_examined': message_flags,
        'biased_language_detected': response_flags,
        'recommendation': 'Ensure the response does not include biased or discriminatory language'
    }
