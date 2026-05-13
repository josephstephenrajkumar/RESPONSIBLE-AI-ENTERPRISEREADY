def evaluate_verifiability(answer):
    citation_count = answer.count('http') + answer.count('https')
    return {
        'verifiability_score': min(1.0, citation_count / 3),
        'citations_found': citation_count,
        'recommendation': 'Support claims with references when possible'
    }
