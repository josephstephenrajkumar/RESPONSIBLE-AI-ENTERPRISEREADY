def evaluate_governance(message):
    policies = ['data retention', 'access control', 'audit']
    return {
        'governance_concern': 'low',
        'policy_scope': policies,
        'recommendation': 'Log audit events and enforce review policies'
    }
