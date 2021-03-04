# translate - A maubot plugin to translate words.
# Copyright (C) 2019 Tulir Asokan
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
from typing import Optional, Tuple, NamedTuple, Set, Dict, TYPE_CHECKING
from importlib import import_module

from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from mautrix.types import RoomID
from maubot import MessageEvent
from maubot.handlers.command import Argument

import re

from .provider import AbstractTranslationProvider

if TYPE_CHECKING:
    from .bot import TranslatorBot

AutoTranslateConfig = NamedTuple("AutoTranslateConfig", main_language=str,
                                 accepted_languages=Set[str])


class TranslationProviderError(Exception):
    pass


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("provider.id")
        helper.copy("provider.args")
        helper.copy("auto_translate")
        helper.copy("response_reply")

    def load_translator(self) -> AbstractTranslationProvider:
        try:
            provider = self["provider.id"]
            mod = import_module(f".{provider}", "translate.provider")
            make = mod.make_translation_provider
        except (KeyError, AttributeError, ImportError) as e:
            raise TranslationProviderError("Failed to load translation provider") from e
        try:
            return make(self["provider.args"])
        except Exception as e:
            raise TranslationProviderError("Failed to initialize translation provider") from e

    def load_auto_translate(self) -> Dict[RoomID, AutoTranslateConfig]:
        atc = {value.get("room_id"): AutoTranslateConfig(value.get("main_language", "en"),
                                                         set(value.get("accepted_languages", [])))
               for value in self["auto_translate"] if "room_id" in value}
        return atc


class LanguageCodeAuto(Argument):
    def __init__(self, name: str, label: str = None, *, required: bool = False):
        super().__init__(name, label=label, required=required, pass_raw=True)

    def match(self, val: str, evt: MessageEvent = None, instance: 'TranslatorBot' = None
              ) -> Tuple[str, Optional[int]]:
        parts = val.split(" ", 1)
        if len(parts) < 2:
            parts.append("")
        if parts[0] in ["setauto", "unsetauto", "help", "show"]:
            return parts[1], parts[0]
        return val, None 


class LanguageCodePair(Argument):
    def __init__(self, name: str, label: str = None, *, required: bool = False):
        super().__init__(name, label=label, required=required, pass_raw=True)

    def match(self, val: str, evt: MessageEvent = None, instance: 'TranslatorBot' = None
              ) -> Tuple[str, Optional[Tuple[list, list]]]:

        if not val or len(val) == 0:
            return val, None
        if val[0] == '[':
            parts = val.split("]", 2)
            if len(parts) == 1:
                return val, None
            elif len(parts) > 1:
                parts[0] = re.split(r'(?:,\s*|\s+)',  parts[0][1:].strip())
                parts[1] = parts[1].strip()
                if len(parts) > 2 and parts[1][0] == '[':
                    parts[1] = re.split(r'(?:,\s*|\s+)',  parts[1][1:])
                else:
                    parts[1] = ']'.join(parts[1:])
                    parts = [parts[0]] + parts[1].split(" ", 1)
                    parts[1] = [parts[1]]
        else:
            parts = val.split(" ", 1)
            if len(parts) == 1:
                return val, None
            else:
                parts[0] = [parts[0]]
                parts[1] = parts[1].strip()
                if parts[1][0] == '[':
                    parts = [parts[0]] + parts[1].split("]", 1)
                    if len(parts) > 2:
                        parts[1] = re.split(r'(?:,\s*|\s+)',  parts[1][1:])
                    else:
                        return val, None
                else:
                    parts = [parts[0]] + parts[1].split(" ", 1)
                    parts[1] = [parts[1]]


        is_supported = (instance.translator.is_supported_language
                        if instance.translator
                        else lambda code: True)

        #check language source
        if 'auto' in parts[0]:
            src_lang = ['auto']
        else:
            src_lang = []
            for i in range(len(parts[0])):
                if is_supported(parts[0][i]):
                    src_lang.append(parts[0][i])
            if len(src_lang) == 0:
                src_lang = ['auto']

        if len(parts) < 3:
            parts.append("")
            if len(parts) < 2:
                parts.append("")

        #check language target
        if src_lang[0] != 'auto' and len(parts[1]) == 1 and not is_supported(parts[1][0]) :
            trg_lang = src_lang
            src_lang = ['auto']
            parts[1] = parts[1][0]
            parts[2] = " ".join(parts[1:])
        else:
            trg_lang = []
            if (len(parts[1]) == 0 or (len(parts[1])==1 and parts[1]=='auto')) and src_lang[0] == 'auto' and parts[2] == "":
                return val, ['auto','auto']
            else:
                for i in range(len(parts[1])):
                    if parts[1][i]!='auto' and is_supported(parts[1][i]):
                        trg_lang.append(parts[1][i])
                if len(trg_lang) == 0:
                    return val, None

        return parts[2], (src_lang, trg_lang)
