def evaluate_explainability(answer):
    return {
        'explanation_provided': bool(answer),
        'explanation_level': 'high-level',
        'recommendation': 'Include step-by-step reasoning when appropriate'
    }
