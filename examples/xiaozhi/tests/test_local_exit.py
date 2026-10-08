import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import xiaozhi.event as events
from xiaozhi.event import Step
from xiaozhi.local_exit import is_local_exit_command
from xiaozhi.xiaozhi import XiaoZhi


class PhraseTests(unittest.TestCase):
    def test_exact_phrases_and_empty_configuration(self):
        config = {'local_exit_commands': ['退出对话', '小七同学再见']}
        self.assertTrue(is_local_exit_command('退出 对话！', config))
        self.assertTrue(is_local_exit_command('小七同学，再见。', config))
        for text in ('关闭主卧灯', '不用了，把灯关掉', '解释退出对话是什么意思', '', None):
            self.assertFalse(is_local_exit_command(text, config))
        self.assertFalse(is_local_exit_command('退出对话', {'local_exit_commands': []}))
        self.assertFalse(is_local_exit_command('退出对话', {'local_exit_commands': '退出对话'}))

    def test_late_events_do_not_rearm_until_explicit_wakeup(self):
        manager = getattr(events, '__EventManager')()
        with patch('xiaozhi.event.get_env', return_value='true'), patch.object(manager, 'start_session') as start:
            manager.on_local_exit()
            previous = manager.session_id
            for _ in range(4):
                manager.on_tts_start('late')
                manager.on_tts_end('late')
                manager.on_stt()
                manager.on_speech(b'late')
            self.assertTrue(manager.conversation_closed)
            self.assertEqual(manager.session_id, previous)
            self.assertEqual(manager.current_step, Step.on_interrupt)
            start.assert_called_once()
            manager.on_wakeup()
            self.assertFalse(manager.conversation_closed)
            manager.on_tts_start('new')
            manager.on_tts_end('new')
            self.assertEqual(start.call_count, 3)


class PacketTests(unittest.IsolatedAsyncioTestCase):
    async def test_closed_conversation_drops_all_late_json(self):
        fake = SimpleNamespace(_handle_tts_message=AsyncMock(), _handle_stt_message=Mock(), _handle_llm_message=Mock())
        with patch('xiaozhi.xiaozhi.EventManager', SimpleNamespace(conversation_closed=True)):
            for packet in ({'type': 'stt', 'text': '退出对话'}, {'type': 'tts', 'state': 'start'},
                           {'type': 'tts', 'state': 'sentence_start', 'text': '再见'},
                           {'type': 'tts', 'state': 'stop'}, {'type': 'llm', 'emotion': 'happy'}):
                await XiaoZhi._on_incoming_json(fake, packet)
        fake._handle_tts_message.assert_not_called()
        fake._handle_stt_message.assert_not_called()
        fake._handle_llm_message.assert_not_called()

    async def test_exit_resolves_old_pending_waiter(self):
        manager = getattr(events, '__EventManager')()
        pending = asyncio.create_task(manager.wait_next_step(manager.session_id))
        await asyncio.sleep(0)
        with patch('xiaozhi.event.get_env', return_value='true'), patch.object(manager, 'start_session'):
            manager.on_local_exit()
        self.assertEqual(await asyncio.wait_for(pending, 1), ('interrupted', None))

    async def test_stt_exit_handler_and_household_sentence(self):
        fake = SimpleNamespace(schedule=Mock(), set_chat_message=Mock())
        manager = SimpleNamespace(on_local_exit=Mock(), on_stt=Mock())
        with patch('xiaozhi.xiaozhi.EventManager', manager), patch('xiaozhi.xiaozhi.get_env', return_value='true'):
            XiaoZhi._handle_stt_message(fake, {'text': '退出 对话！'})
            manager.on_local_exit.assert_called_once()
            manager.on_stt.assert_not_called()
            fake.schedule.assert_not_called()
            XiaoZhi._handle_stt_message(fake, {'text': '关闭主卧灯'})
            manager.on_stt.assert_called_once()
            self.assertEqual(fake.schedule.call_count, 1)

    async def test_gui_does_not_enable_cli_exit(self):
        manager = getattr(events, '__EventManager')()
        with patch('xiaozhi.event.get_env', return_value=False), patch.object(manager, 'start_session') as start:
            manager.on_local_exit()
        self.assertFalse(manager.conversation_closed)
        start.assert_not_called()

    async def test_queued_tts_start_cannot_start_stream_after_exit(self):
        fake = SimpleNamespace(set_device_state=Mock())
        with patch('xiaozhi.xiaozhi.EventManager', SimpleNamespace(conversation_closed=True)):
            XiaoZhi._handle_tts_start(fake)
        fake.set_device_state.assert_not_called()

    async def test_exit_uses_real_abort_path_without_listening(self):
        manager = getattr(events, '__EventManager')()
        abort = AsyncMock()
        protocol = SimpleNamespace(send_abort_speaking=AsyncMock())
        app = SimpleNamespace(loop=asyncio.get_running_loop(), abort_tts_output=abort,
                              set_device_state=Mock(), protocol=protocol)
        vad = SimpleNamespace(resume=Mock())
        with patch('xiaozhi.event.get_env', return_value='true'), patch('xiaozhi.event.get_xiaozhi', return_value=app), \
             patch('xiaozhi.event.get_vad', return_value=vad), patch('xiaozhi.event.get_audio_codec'), \
             patch('xiaozhi.event.get_speaker'):
            manager.on_local_exit()
            await asyncio.wrap_future(manager.session_future)
        abort.assert_awaited_once()
        protocol.send_abort_speaking.assert_awaited_once()
        vad.resume.assert_not_called()


if __name__ == '__main__':
    unittest.main()
