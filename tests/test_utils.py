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
from eeweather.utils import lazy_property


def test_lazy_property():
    class NotLazy(object):
        n_times = 1

        @property
        def tryme(self):
            times = self.n_times
            self.n_times += 1
            return times

    class Lazy(object):
        n_times = 1

        @lazy_property
        def tryme(self):
            times = self.n_times
            self.n_times += 1
            return times

    not_lazy = NotLazy()
    assert not_lazy.tryme == 1
    assert not_lazy.tryme == 2  # called twice

    lazy = Lazy()
    assert lazy.tryme == 1
    assert lazy.tryme == 1  # only called once
