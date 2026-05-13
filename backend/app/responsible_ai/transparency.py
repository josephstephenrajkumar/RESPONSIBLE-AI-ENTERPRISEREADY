def evaluate_transparency(answer):
    transparency = 'full' if 'I think' in answer or 'I am' in answer else 'partial'
    return {
        'transparency_level': transparency,
        'recommendation': 'State assumptions clearly and disclose uncertainty'
    }
