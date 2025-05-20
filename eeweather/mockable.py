#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""

Copyright 2018-2023 OpenEEmeter contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

"""
"""
Usage:

    # module.py
    import mockable

    @mockable.mockable
    def expensive_function():
        pass

    def function_a():
        mockable.expensive_function()


    # test_module.py
    import pytest

    @pytest.fixture
    def mock_expensive_function(monkeypatch):
        def cheap_func():
            pass
        monkeypatch.setattr(
            'mockable.expensive_function',
            cheap_func
        )

    def test_function_a(mock_expensive_function):
        function_a()

"""

import sys


def mockable():
    def decorator(func):
        setattr(sys.modules[__name__], func.__name__, func)
        return func

    return decorator
