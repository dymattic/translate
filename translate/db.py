# translate - A maubot plugin to subscribe to RSS/Atom feeds.
# Copyright (C) 2020 Tulir Asokan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
from typing import Iterable, NamedTuple, List, Optional, Dict, Tuple
from datetime import datetime
from string import Template

from sqlalchemy import (Column, String, Integer, DateTime, Text, Boolean, ForeignKey,
                        Table, MetaData,
                        select, and_, true)
from sqlalchemy.engine.base import Engine

from mautrix.types import UserID, RoomID

Autotranslate = NamedTuple("Autotranslate", room_id=RoomID, user_id=UserID, source_lang=str, target_lang=str,
        provider=str)


class Database:
    db: Engine
    autotranslate: Table
    version: Table

    def __init__(self, db: Engine) -> None:
        self.db = db
        metadata = MetaData()
        self.autotranslate = Table("autotranslate", metadata,
                                  Column("room_id", String(255), primary_key=True),
                                  Column("user_id", String(255), nullable=False),
                                  Column("source_lang", String(255), nullable=False),
                                  Column("target_lang", String(255), nullable=False),
                                  Column("provider", String(255))
                                  )
        self.version = Table("version", metadata,
                             Column("version", Integer, primary_key=True))
        self.upgrade()

    def upgrade(self) -> None:
        self.db.execute("CREATE TABLE IF NOT EXISTS version (version INTEGER PRIMARY KEY)")
        try:
            version, = next(self.db.execute(select([self.version.c.version])))
        except (StopIteration, IndexError):
            version = 0
        if version == 0:
            self.db.execute("""CREATE TABLE IF NOT EXISTS autotranslate (
                room_id VARCHAR(255) NOT NULL,
                user_id VARCHAR(255) NOT NULL,
                source_lang VARCHAR(255) NOT NULL,
                target_lang VARCHAR(255) NOT NULL,
                provider VARCHAR(255) NOT NULL
            )""")
            version = 1
        self.db.execute(self.version.delete())
        self.db.execute(self.version.insert().values(version=version))

    def get_autotranslate_by_room(self, room_id: RoomID) -> Optional[Autotranslate]:
        rows = self.db.execute(select([self.autotranslate]).where(self.autotranslate.c.room_id == room_id))
        try:
            row = next(rows)
            return Autotranslate(*row)
        except (ValueError, StopIteration):
            return None

    def update_room_id(self, old: RoomID, new: RoomID) -> None:
        self.db.execute(self.autotranslate.update()
                        .where(self.autotranslate.c.room_id == old)
                        .values(room_id=new))

    def create_autotranslate(self, room_id: RoomID, user_id: UserID, source_lang: str, target_lang: str, provider: str) -> bool :
        res = self.db.execute(self.autotranslate.insert().values(room_id=room_id, user_id=user_id,
            source_lang=source_lang, target_lang=target_lang, provider=provider))
        return True

    def update_autotranslate(self, room_id: RoomID, user_id: UserID, source_lang: str, target_lang: str, provider: str) -> None :
        tbl = self.autotranslate
        self.db.execute(tbl.update()
                        .where(tbl.c.room_id == room_id)
                        .values(user_id=user_id, source_lang=source_lang, target_lang=target_lang, provider=provider))

    def remove_autotranslate(self, room_id: RoomID) -> None:
        tbl = self.autotranslate
        self.db.execute(tbl.delete().where(and_(tbl.c.room_id == room_id)))

