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
from pprint import pprint
from typing import Optional, Tuple, Type, Dict, Union

from mautrix.util.config import BaseProxyConfig
from mautrix.types import RoomID, EventType, MessageType
from maubot import Plugin, MessageEvent
from maubot.handlers import command, event

from .provider import AbstractTranslationProvider
from .util import Config, LanguageCodePair, LanguageCodeAuto, TranslationProviderError, AutoTranslateConfig
from .db import Database, Autotranslate

try:
    import langdetect
    from langdetect.lang_detect_exception import LangDetectException
except ImportError:
    langdetect = None
    LangDetectException = None


class TranslateBotError(Exception):
    pass


class TranslatorBot(Plugin):
    db: Database
    translator: Optional[AbstractTranslationProvider]
    auto_translate: Dict[RoomID, AutoTranslateConfig]
    config: Config

    simmilar_languages = [["ko", "zh-CN", "zh-TW", "zh-cn"], ["de", "fi", "pl", "hu"]]

    async def start(self) -> None:
        await super().start()
        self.db = Database(self.database)
        self.on_external_config_update()

    def on_external_config_update(self) -> None:
        self.translator = None
        self.config.load_and_update()
        self.auto_translate = self.config.load_auto_translate()
        try:
            self.translator = self.config.load_translator()
        except TranslationProviderError:
            self.log.exception("")

    async def subscribe(self, evt: MessageEvent, source_lang: list, target_lang: list, provider: str) -> None:
        # if not await self.can_manage(evt):
        #    self.log.warn("-------------")
        #    return
        room_id = self.db.get_autotranslate_by_room(evt.room_id)
        source_lang = ' '.join(source_lang)
        target_lang = ' '.join(target_lang)
        if not room_id:
            self.db.create_autotranslate(room_id=evt.room_id, user_id=evt.sender, source_lang=source_lang,
                                         target_lang=target_lang, provider=provider)
        else:
            self.db.update_autotranslate(room_id=evt.room_id, user_id=evt.sender, source_lang=source_lang,
                                         target_lang=target_lang, provider=provider)
        await self.show_subscriptions(evt=evt)

    async def unsubscribe(self, evt: MessageEvent) -> None:
        room_id = self.db.get_autotranslate_by_room(evt.room_id)
        if room_id:
            self.db.remove_autotranslate(room_id=evt.room_id)
        await self.show_subscriptions(evt=evt)

    def subscriptions(self, evt: MessageEvent) -> Union[str, None]:
        atc = self.db.get_autotranslate_by_room(evt.room_id)
        if atc:
            source_lang_t = ", ".join(atc.source_lang.split(" "))
            target_lang_t = ", ".join(atc.target_lang.split(" "))
            return (
                f"Messages are translated automatically from _[{source_lang_t}]_ -> _[{target_lang_t}]_ by __{atc.provider}__ in this room. Be aware that the provider will read all message content.")
        else:
            return f"No messages in this room are automatically translated."

    async def show_subscriptions(self, evt: MessageEvent) -> None:
        await evt.reply(self.subscriptions(evt))

    def is_acceptable(self, lang: str, accepted_languages: list) -> Union[str, bool]:
        if len(accepted_languages) == 0 or lang in accepted_languages:
            return lang
        for accepted_language in accepted_languages:
            for simmilar_lang in self.simmilar_languages:
                if accepted_language in simmilar_lang and lang in simmilar_lang:
                    return accepted_language
        return False

    def is_acceptable_soft(self, lang: str, accepted_languages: list) -> bool:
        return True if (len(accepted_languages) == 0 or lang in accepted_languages) else False

    @classmethod
    def get_config_class(cls) -> Type['BaseProxyConfig']:
        return Config

    @event.on(EventType.ROOM_MESSAGE)
    async def event_handler(self, evt: MessageEvent) -> None:
        if (
                langdetect is None
                or evt.content.msgtype == MessageType.NOTICE
                or evt.sender == self.client.mxid
                or evt.content.body[0:3] == '!tr'
        ):
            self.log.info(pprint(evt.content.body))
            return

        # get atc_config from db if existent ( database config = higher prio )
        atc_db = self.db.get_autotranslate_by_room(evt.room_id)
        if atc_db:
            atc = atc_db
            accepted_languages = atc.source_lang.split(" ")
            main_language = atc.target_lang.split(" ")

        else:
            # acquire auto translate configuration from file
            try:
                atc = self.auto_translate[evt.room_id]
                accepted_languages = atc.accepted_languages
                main_language = atc.main_language
            except KeyError:
                self.log.warning(f"Key error occurred: {KeyError}")
                return

        detected_lang = langdetect.detect(evt.content.body)
        self.log.warn(f"translation language detected: {detected_lang}")
        if self.is_acceptable_soft(detected_lang, accepted_languages):
            for atc_main_language in main_language:
                if atc_main_language != detected_lang:
                    try:
                        result = await self.translator.translate(evt.content.body, to_lang=atc_main_language,
                                                                 from_lang=detected_lang)
                    except:
                        await evt.respond(f"[{evt.sender}](https://matrix.to/#/{evt.sender}) "
                                          f"Provider __{self.config['provider']['id']}__ not reachable!!")
                        return
                    await evt.respond(f"[{evt.sender}](https://matrix.to/#/{evt.sender}) "
                                      f"*(in {result.source_language}) "
                                      f"__{atc_main_language}__*: "
                                      f"{result.text}")
        else:
            try:
                result = await self.translator.translate(evt.content.body, to_lang=main_language[0])
            except:
                await evt.respond(f"[{evt.sender}](https://matrix.to/#/{evt.sender}) "
                                  f"Provider __{self.config['provider']['id']}__ not reachable!!")
                return
            from_lang = 'auto'
            if self.is_acceptable(result.source_language, accepted_languages):
                from_lang = result.source_language
                await evt.respond(f"[{evt.sender}](https://matrix.to/#/{evt.sender}) "
                                  f"*(in {from_lang}) "
                                  f"__{main_language[0]}__*: "
                                  f"{result.text}")
                for atc_main_language in main_language[1:]:
                    try:
                        result = await self.translator.translate(evt.content.body, to_lang=atc_main_language,
                                                                 from_lang=from_lang)
                    except:
                        await evt.respond(f"[{evt.sender}](https://matrix.to/#/{evt.sender}) "
                                          f"Provider __{self.config['provider']['id']}__ not reachable!!")
                        return
                    self.log.warn(f"language detected --: {result.source_language}  {atc_main_language}")
                    accept_lang = self.is_acceptable(result.source_language, accepted_languages)
                    if (accept_lang
                            and result.source_language != atc_main_language
                            and result.text != evt.content.body):
                        await evt.respond(f"[{evt.sender}](https://matrix.to/#/{evt.sender}) "
                                          f"*(in {from_lang}) "
                                          f"__{atc_main_language}__*: "
                                          f"{result.text}")
            else:
                for atc_main_language in main_language:
                    for atc_accepted_language in accepted_languages:
                        if atc_main_language != atc_accepted_language:
                            try:
                                result = await self.translator.translate(evt.content.body, to_lang=atc_main_language,
                                                                         from_lang=atc_accepted_language)
                            except:
                                await evt.respond(f"[{evt.sender}](https://matrix.to/#/{evt.sender}) "
                                                  f"Provider __{self.config['provider']['id']}__ not reachable!!")
                                return
                            self.log.warn(f"language detected 01: {result.source_language}  {atc_main_language}")
                            if (result.source_language != atc_main_language
                                    and result.text.strip().lower() != evt.content.body.strip().lower()):
                                await evt.respond(f"[{evt.sender}](https://matrix.to/#/{evt.sender}) "
                                                  f"*(in {atc_accepted_language}) "
                                                  f"__{atc_main_language}__*: "
                                                  f"{result.text}")

    @command.new("translate", aliases=["tr"])
    @LanguageCodeAuto("auto", required=False)
    @LanguageCodePair("language", required=False)
    @command.argument("text", pass_raw=True, required=False)
    async def command_handler(self, evt: MessageEvent, language: Optional[Tuple[list, list]], auto: str,
                              text: str) -> None:
        help_response = """__Usage:__ !tr  <subcommand> [...]
- [from] <to> [text or reply to message] - Translate text.
  example:
  - `!tr fr fi la maison est magnifique` -> French to Finnish
  - `!tr [en, fi] la maison est magnifique` -> Any language to English and Finnish
- setauto [<from>, <from>] [<to>, <to>] - Automatically translate text in this room.
- setauto [<to>] - Automatically translate all languages to a list of languages in this room.
- unsetauto - Stop automatically translating text in this room.
- show - Show automatic translation settings for this room.

"""
        if auto == 'setauto' and not language:
            await evt.reply("Usage: !translate setauto [from, from] [to, to, ...]")
            return
        if auto == 'setauto' and language[1] == 'auto':
            await self.unsubscribe(evt=evt)
            return
        if auto == 'setauto' and language:
            await self.subscribe(evt=evt, source_lang=language[0], target_lang=language[1],
                                 provider=self.config["provider"]["id"])
            return
        if auto == 'unsetauto':
            await self.unsubscribe(evt=evt)
            return
        if auto == 'show':
            await self.show_subscriptions(evt=evt)
            return
        if not language or auto == 'help':
            await evt.reply(help_response + self.subscriptions(evt))
            return
        if language[1] == 'auto':
            await self.unsubscribe(evt=evt)
            return
        if not self.config["response_reply"]:
            evt.disable_reply = True
        if not self.translator:
            self.log.warn("Translate command used, but translator not loaded")
            return
        if not text and evt.content.get_reply_to():
            reply_evt = await self.client.get_event(evt.room_id, evt.content.get_reply_to())
            text = reply_evt.content.body
        if not text:
            await evt.reply("Usage: !translate [from] <to> [text or reply to message]")
            return
        results = []
        for target in language[1]:
            for source in language[0]:
                self.log.warn(f"cmd: language given:    {source}  {target}")
                result = await self.translator.translate(text, to_lang=target, from_lang=source)
                if source == 'auto':
                    results.append(f"_{result.source_language}_ -> __{target}__: {result.text}")
                else:
                    results.append(f"__{target}__: {result.text}")
                self.log.warn(f"cmd: language detected: {source}  {target}")
        if len(result) > 0:
            await evt.reply("<br>\n".join(results), allow_html=True)
        return
