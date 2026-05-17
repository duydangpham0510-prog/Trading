from __future__ import annotations

from django import forms

from dashboard.services import get_function_definition


class DynamicFunctionForm(forms.Form):
    def __init__(self, function_id: str, *args, **kwargs):
        self.function_id = function_id
        definition = get_function_definition(function_id)
        self.definition = definition
        super().__init__(*args, **kwargs)

        if definition is None:
            return

        for field_name, config in definition["param_schema"].items():
            field_type = config.get("type", "string")
            required = config.get("required", False)
            default = config.get("default", "")
            if field_type == "date":
                field = forms.DateField(required=required, initial=default, widget=forms.DateInput(attrs={"type": "date"}))
            elif field_type == "select":
                choices = [(opt, opt) for opt in config.get("options", [])]
                field = forms.ChoiceField(choices=choices, required=required, initial=default, widget=forms.Select())
            else:
                field = forms.CharField(required=required, initial=default)
            self.fields[field_name] = field
