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
import os
import json

try:
    from sqlalchemy import (
        create_engine,
        MetaData,
        Table,
        Column,
        String,
        DateTime,
    )
    from sqlalchemy.orm import Session
    from sqlalchemy.sql import select, func
    from sqlalchemy.exc import IntegrityError
except ImportError:  # pragma: no cover
    has_sqlalchemy = False
else:
    has_sqlalchemy = True
import pytz


def get_datetime_if_exists(data):
    if data is None:
        return None
    else:
        dt = data[0]
    if is_tz_naive(dt):
        return pytz.UTC.localize(data[0])
    else:
        return dt


def is_tz_naive(dt):
    return dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None


class KeyValueStore(object):
    def __init__(self, url=None):
        if not has_sqlalchemy:  # pragma: no cover
            raise ImportError("KeyValueStore requires sqlalchemy.")
        self._prepare_db(url)

    def __repr__(self):
        return 'KeyValueStore("{}")'.format(self.url)

    def _get_url(self):  # pragma: no cover (tests always provide url)
        url = os.environ.get("EEWEATHER_CACHE_URL")
        if url is None:
            directory = "{}/.eeweather".format(os.path.expanduser("~"))
            if not os.path.exists(directory):
                os.makedirs(directory)
            url = "sqlite:///{}/cache.db".format(directory)
        return url

    def _prepare_db(self, url=None):
        # set url
        if url is None:  # pragma: no cover (tests always provide url)
            url = self._get_url()
        self.url = url

        self.eng = create_engine(url)
        metadata = MetaData()

        tbl_items = Table(
            "items",
            metadata,
            Column("key", String, unique=True, index=True),  # arbitrary unique key
            Column("data", String),  # arbitrary json
            Column("updated", DateTime(timezone=True)),  # time of last transaction
        )

        # only create if not already created
        tbl_items.create(checkfirst=True, bind=self.eng)

        self.items = tbl_items

    def key_exists(self, key):
        s = select(self.items.c.key).where(self.items.c.key == key)
        with Session(self.eng) as session:
            result = session.execute(s)
            return result.fetchone() is not None

    def save_json(self, key, data):
        data = json.dumps(data, separators=(",", ":"))
        updated = func.now()
        try:
            s = self.items.insert().values(key=key, data=data, updated=updated)
            with Session(self.eng) as session:
                session.execute(s)
                session.commit()
        except IntegrityError:
            s = (
                self.items.update()
                .where(self.items.c.key == key)
                .values(key=key, data=data, updated=updated)
            )
            with Session(self.eng) as session:
                session.execute(s)
                session.commit()

    def retrieve_json(self, key):
        s = select(self.items.c.data).where(self.items.c.key == key)
        with Session(self.eng) as session:
            result = session.execute(s)
            data = result.fetchone()
            if data is None:
                return None
            else:
                return json.loads(data[0])

    def key_updated(self, key):
        s = select(self.items.c.updated).where(self.items.c.key == key)
        with Session(self.eng) as session:
            result = session.execute(s)
            data = result.fetchone()
            return get_datetime_if_exists(data)

    def clear(self, key=None):
        if key is None:
            s = self.items.delete()
        else:
            s = self.items.delete().where(self.items.c.key == key)
        with Session(self.eng) as session:
            session.execute(s)
            session.commit()
