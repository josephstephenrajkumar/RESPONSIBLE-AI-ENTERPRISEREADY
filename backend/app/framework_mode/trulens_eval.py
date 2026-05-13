def evaluate_explainability(answer):
    return {
        'explanation_provided': bool(answer),
        'explanation_level': 'high-level',
        'recommendation': 'Evaluate rationale quality with model cards'
    }
