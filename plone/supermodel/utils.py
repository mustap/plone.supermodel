import os.path
import sys
import re

from elementtree import ElementTree

from zope.schema.interfaces import IField, IFromUnicode, IDict, ICollection

from plone.supermodel.interfaces import XML_NAMESPACE, IToUnicode

_marker = object()
no_ns_re = re.compile('^{\S+}')

def ns(name, prefix=XML_NAMESPACE):
    """Return the element or attribute name with the given prefix
    """
    
    return u"{%s}%s" % (prefix, name)

def no_ns(name):
    """Return the tag with no namespace
    """
    return no_ns_re.sub('', name)

def indent(node, level=0):
    
    node_indent = level * "  "
    child_indent = (level + 1) * "  "
    
    # node has childen
    if len(node):
        
        # add indent before first child node
        if not node.text or not node.text.strip():
            node.text = "\n" + child_indent
        
        # let each child indent itself
        last_idx = len(node) - 1
        for idx, child in enumerate(node):
            indent(child, level + 1)
            
            # add a tail for the next child node...
            if idx != last_idx:
                if not child.tail or not child.tail.strip():
                    child.tail = "\n" + child_indent
            # ... or for the closing element of this node
            else:
                if not child.tail or not child.tail.strip():
                    child.tail = "\n" + node_indent

def pretty_xml(tree):
    indent(tree)
    return ElementTree.tostring(tree)

def field_typecast(field, value):
    typecast = getattr(field, '_type', None)
    if typecast is not None:
        if not isinstance(typecast, (list, tuple)):
            typecast = (typecast,)
        for tc in reversed(typecast):
            if callable(tc):
                try:
                    value = tc(value)
                    break
                except:
                    pass
    return value

def element_to_value(field, element, default=_marker):
    """Read the contents of an element that is assumed to represent a value
    allowable by the given field. 
    
    If converter is given, it should be an IToUnicode instance.
    
    If not, the field will be adapted to this interface to obtain a converter.
    """
    
    value = default
    
    if IDict.providedBy(field):
        key_converter = IFromUnicode(field.key_type)
        value_converter = IFromUnicode(field.value_type)
        
        value = {}
        for child in element:
            if child.tag.lower() != 'element':
                continue
            
            key_text = child.attrib.get('key', None)
            if key_text is None:
                k = None
            else:
                k = key_converter.fromUnicode(unicode(key_text))
            
            value_text = child.text
            if value_text is None:
                v = None
            else:
                v= value_converter.fromUnicode(unicode(value_text))
            
            value[k] = v
        value = field_typecast(field, value)
    
    elif ICollection.providedBy(field):
        value_converter = IFromUnicode(field.value_type)
        value = []
        for child in element:
            if child.tag.lower() != 'element':
                continue
            text = child.text
            if text is None:
                value.append(None)
            else:
                value.append(value_converter.fromUnicode(unicode(text)))
        value = field_typecast(field, value)
    
    # Unicode
    else:
        text = element.text
        if text is None:
            value = field.missing_value
        else:
            converter = IFromUnicode(field)
            value = converter.fromUnicode(unicode(text))
      
    return value
    
def value_to_element(field, value, name=None, force=False):
    """Create and return an element that describes the given value, which is
    assumed to be valid for the given field.
    
    If name is given, this will be used as the new element name. Otherwise,
    the field's __name__ attribute is consulted.
    
    If force is True, the value will always be written. Otherwise, it is only
    written if it is not equal to field.missing_value.
    """

    if name is None:
        name = field.__name__

    child = ElementTree.Element(name)

    if force or value != field.missing_value:

        if IDict.providedBy(field):
            key_converter = IToUnicode(field.key_type)
            value_converter = IToUnicode(field.value_type)

            for k, v in value.items():
                list_element = ElementTree.Element('element')
                list_element.attrib['key'] = key_converter.toUnicode(k)
                list_element.text = value_converter.toUnicode(v)
                child.append(list_element)

        elif ICollection.providedBy(field):
            value_converter = IToUnicode(field.value_type)
            for v in value:
                list_element = ElementTree.Element('element')
                list_element.text = value_converter.toUnicode(v)
                child.append(list_element)

        else:
            converter = IToUnicode(field)
            child.text = converter.toUnicode(value)

    return child

def relative_to_calling_package(filename, calling_frame=2):
    """If the filename is not an absolute path, make it into an absolute path
    by calculating the relative path from the module that called the function
    at 'calling_frame' steps down the stack.
    """
    if os.path.isabs(filename):
        return filename
    else:
        name = sys._getframe(calling_frame).f_globals['__name__']
        module = sys.modules[name]
        if hasattr(module, '__path__'):
            directory = module.__path__[0]
        elif "." in name:
            parent_module = name[:name.rfind('.')]
            directory = sys.modules[parent_module].__path__[0]
        else:
            directory = name
        directory = os.path.abspath(directory)
        return os.path.abspath(os.path.join(directory, filename))

def sorted_fields(schema):
    """Like getFieldsInOrder, but does not include fields from bases
    """
    fields = []
    for name in schema.names(all=False):
        field = schema[name]
        if IField.providedBy(field):
            fields.append((name, field,))
    fields.sort(key=lambda item: item[1].order)
    return fields

def merged_tagged_value_dict(schema, name):
    """Look up the tagged value 'name' in schema and all its bases, assuming
    that the value under 'name' is a dict. Return a dict that consists of
    all dict items, with those from more-specific interfaces overriding those
    from more-general ones.
    """
    tv = {}
    for iface in reversed(schema.__iro__):
        tv.update(iface.queryTaggedValue(name, {}))
    return tv

def merged_tagged_value_list(schema, name):
    """Look up the tagged value 'name' in schema and all its bases, assuming
    that the value under 'name' is a list. Return a list that consists of
    all elements from all interfaces and base interfaces, with values from
    more-specific interfaces appearing at the end of the list.
    """
    tv = []
    for iface in reversed(schema.__iro__):
        tv.extend(iface.queryTaggedValue(name, []))
    return tv

def sync_schema(source, dest, overwrite=False, sync_bases=False):
    """Copy attributes and tagged values from the source to the destination.
    If overwrite is False, do not overwrite attributes or tagged values that
    already exist or delete ones that don't exist in source.
    """

    if overwrite:    
        to_delete = set()
    
        # Delete fields in dest, but not in source
        for name, field in sorted_fields(dest):
            if name not in source:
                to_delete.add(name)
    
        for name in to_delete:
            # delattr(dest, name)
            del dest._InterfaceClass__attrs[name]
            if hasattr(dest, '_v_attrs'):
                del dest._v_attrs[name]

    # Add fields that are in source, but not in dest
    
    for name, field in sorted_fields(source):
        if overwrite or name not in dest:
            
            clone = field.__class__.__new__(field.__class__)
            clone.__dict__.update(field.__dict__)
            clone.interface = dest
            clone.__name__ = name
            
            # setattr(dest, name, clone)
            dest._InterfaceClass__attrs[name] = clone
            if hasattr(dest, '_v_attrs'):
                dest._v_attrs[name] = clone

    # Copy tagged values
    
    dest_tags = set(dest.getTaggedValueTags())
    for tag in source.getTaggedValueTags():
        if overwrite or tag not in dest_tags:
            value = source.getTaggedValue(tag)
            dest.setTaggedValue(tag, value)

    # Sync bases
    if sync_bases:
        bases = list(source.__bases__)
        if not overwrite:
            for base in dest.__bases__:
                if base not in bases:
                    bases.append(base)
        dest.__bases__ = tuple(bases)