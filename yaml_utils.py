def yaml_safe_value(value):
    """
    Format a value for safe YAML usage:
    - Multiline values: Use block literal (|)
    - Values with double quotes: Use single quotes
    - Values with colons or starting with dash: Use double quotes
    - Other values: Use double quotes
    """
    if value is None:
        return '""'
    value = str(value)
    if '\n' in value:
        # Block literal, indented
        indented = "\n  ".join(value.splitlines())
        return f"|\n  {indented}"
    elif '"' in value:
        # Use single quotes and escape single quotes
        safe = value.replace("'", "''")
        return f"'{safe}'"
    elif ':' in value or value.strip().startswith('- '):
        # Use double quotes for colons or looks like a list
        safe = value.replace('"', '\\"')
        return f'"{safe}"'
    else:
        safe = value.replace('"', '\\"')
        return f'"{safe}"'
