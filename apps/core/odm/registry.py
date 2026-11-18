"""Model registry: resolves 'app.Model' references and lists relations for deletion."""
_models = {}       # 'app_label.ModelName' (lower) and 'ModelName' (lower) -> class
_all = []


def register(model, app_label):
    _all.append(model)
    _models[f'{app_label}.{model.__name__}'.lower()] = model
    _models.setdefault(model.__name__.lower(), model)


def alias(name, model):
    _models[name.lower()] = model


def resolve(ref):
    if isinstance(ref, type):
        return ref
    try:
        return _models[ref.lower()]
    except KeyError:
        raise LookupError(f'ODM model not found: {ref}') from None


def all_models():
    return list(_all)


def relations_to(model):
    """(source_model, field) for every ForeignKey / ManyToMany pointing at `model`."""
    out = []
    for src in _all:
        for field in src._meta.fields:
            if field.is_relation:
                try:
                    if field.remote_model is model:
                        out.append((src, field))
                except LookupError:
                    continue
    return out


def reverse_accessor(model, name):
    """Find a reverse relation exposed on `model` under related_name `name`."""
    for src, field in relations_to(model):
        if field.related_name == name:
            return src, field
    return None
