"""Plain-text message customization; routing always uses original engine metadata."""
import copy
from string import Formatter

ENGINES = {'l1': 'L1 CAPITAL', 'twelve': '12-STEP', 'market': 'Market alerts'}
KINDS = ('signal', 'result', 'wait', 'withdrawal', 'daily', 'radar', 'rsi', 'streak')
VARIABLES = {'original': 'Complete original engine message', 'title': 'Original first line',
             'body': 'Original details below the title', 'engine': 'Strategy / channel name',
             'category': 'Message type'}
MESSAGE_DEFAULTS = {'templates': {f'{e}.{k}': '{original}' for e in ENGINES for k in KINDS}}

def validate_template(template):
    if isinstance(template,dict):
        if set(template)!={'heading','before','after'} or any(not isinstance(v,str) or len(v)>800 for v in template.values()) or sum(map(len,template.values()))>1800:
            raise ValueError('Use a heading, opening text and closing text, up to 1800 characters in total.')
        return copy.deepcopy(template)
    if not isinstance(template, str) or not template.strip() or len(template) > 1800:
        raise ValueError('Message template must contain 1–1800 characters.')
    try:
        for _, field, spec, conversion in Formatter().parse(template):
            if field is not None and (field not in VARIABLES or spec or conversion):
                raise ValueError('Use only the listed placeholders, without formatting options.')
    except ValueError:
        raise ValueError('Invalid placeholder. Use {original}, {title}, {body}, {engine} or {category}; {{ and }} print braces.')
    return template

def validate_messages(value):
    if not isinstance(value, dict) or set(value) != {'templates'} or not isinstance(value['templates'], dict) or set(value['templates']) != set(MESSAGE_DEFAULTS['templates']):
        raise ValueError('Provide all message templates.')
    for template in value['templates'].values():
        validate_template(template)
    return copy.deepcopy(value)

def render_message(template, original, engine, category):
    validate_template(template)
    original = str(original)
    if isinstance(template,dict):
        text='\n\n'.join(v.strip() for v in (template['heading'],template['before'],original,template['after']) if v.strip())
        fallback=len(text.encode('utf-16-le'))//2>4096
        return {'text':original if fallback else text,'fallback':fallback,'details_appended':False}
    title, _, body = original.partition('\n')
    fields = {f for _, f, _, _ in Formatter().parse(template) if f is not None}
    text = template.format(original=original, title=title, body=body,
                           engine=ENGINES.get(engine, engine), category=category)
    # Keep issued stake/issue/result facts available even when a custom header is used.
    appended = not fields.intersection({'original', 'body'})
    if appended:
        text += '\n\nENGINE DETAILS\n' + original
    if 'body' in fields and not fields.intersection({'original', 'title'}):
        text += '\n\nENGINE HEADER\n' + title
        appended = True
    fallback = len(text.encode('utf-16-le')) // 2 > 4096
    return {'text': original if fallback else text, 'fallback': fallback, 'details_appended': appended}
