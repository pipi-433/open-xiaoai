import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from xiaozhi.text_corrections import correct_text
from xiaozhi.xiaozhi import XiaoZhi


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.file = Path(self.directory.name) / 'asr-corrections.json'

    def write(self, rules, enabled=True):
        self.file.write_text(json.dumps({'version': 1, 'enabled': enabled, 'rules': rules}, ensure_ascii=False), encoding='utf-8')

    def test_committed_template_is_empty_and_disabled(self):
        template = Path('/app/asr-corrections.json')
        config = json.loads(template.read_text())
        self.assertFalse(config['enabled'])
        self.assertEqual(config['rules'], [])
        self.assertEqual(correct_text('普通测试句子', template), '普通测试句子')

    def test_empty_and_disabled_leave_text_unchanged(self):
        self.write([])
        self.assertEqual(correct_text('普通测试句子', self.file), '普通测试句子')
        self.write([{'source': '名称甲', 'target': '名称乙'}], enabled=False)
        self.assertEqual(correct_text('名称甲', self.file), '名称甲')

    def test_exact_mode_does_not_replace_inside_commands(self):
        self.write([{'source': '名称甲', 'target': '名称乙'}])
        self.assertEqual(correct_text('名称甲', self.file), '名称乙')
        self.assertEqual(correct_text('打开名称甲', self.file), '打开名称甲')

    def test_literal_name_replacement_preserves_actions_and_numbers(self):
        self.write([{'source': '名称甲', 'target': '名称乙', 'mode': 'name'}])
        self.assertEqual(correct_text('不要打开名称甲，设到26度', self.file), '不要打开名称乙，设到26度')

    def test_replacements_are_single_pass_longest_first(self):
        self.write([{'source': '名称甲', 'target': '名称乙', 'mode': 'name'},
                    {'source': '名称乙', 'target': '名称丙', 'mode': 'name'},
                    {'source': '名称甲长', 'target': '名称丁', 'mode': 'name'}])
        self.assertEqual(correct_text('名称甲长和名称甲', self.file), '名称丁和名称乙')

    def test_regex_metacharacters_are_literal(self):
        self.write([{'source': 'A.B', 'target': 'C.D', 'mode': 'name'}])
        self.assertEqual(correct_text('A.B与AXB', self.file), 'C.D与AXB')

    def test_conflicting_rules_keep_original(self):
        self.write([{'source': '名称甲', 'target': '名称乙'}, {'source': '名称甲', 'target': '名称丙'}])
        self.assertEqual(correct_text('名称甲', self.file), '名称甲')

    def test_control_negation_and_quantity_changes_are_rejected(self):
        for source, target in [('打开', '关闭'), ('不要', '需要'), ('26', '28'), ('二十六度', '二十八度')]:
            with self.subTest(source=source):
                self.write([{'source': source, 'target': target, 'mode': 'name'}])
                self.assertEqual(correct_text(source, self.file), source)

    def test_malformed_missing_and_oversized_tables_keep_original(self):
        self.assertEqual(correct_text('原文', self.file), '原文')
        for contents in ('{bad json', '[]', '{"version":2,"enabled":true,"rules":[]}', ' ' * 65537):
            self.file.write_text(contents)
            self.assertEqual(correct_text('原文', self.file), '原文')

    def test_bad_rules_are_not_partially_applied(self):
        for bad in ({'source': '', 'target': '名称乙'}, {'source': '名称丙', 'target': ''},
                    {'source': '名称丙', 'target': '名称丁', 'mode': 'regex'}, None):
            self.write([{'source': '名称甲', 'target': '名称乙'}, bad])
            self.assertEqual(correct_text('名称甲', self.file), '名称甲')

    def test_local_override_wins_without_changing_template(self):
        self.write([], enabled=False)
        local = self.file.with_name('asr-corrections.local.json')
        local.write_text(json.dumps({'version': 1, 'enabled': True, 'rules': [{'source': '名称甲', 'target': '名称乙'}]}))
        self.assertEqual(correct_text('名称甲', self.file), '名称乙')
        self.assertFalse(json.loads(self.file.read_text())['enabled'])

    def test_non_string_inputs_are_unchanged(self):
        for text in ('', None, 123):
            self.assertEqual(correct_text(text, self.file), text)

    def test_bridge_display_receives_correction_after_raw_exit_check(self):
        schedule = Mock()
        fake = SimpleNamespace(schedule=schedule, set_chat_message=Mock())
        events = SimpleNamespace(on_local_exit=Mock(), on_stt=Mock())
        with patch('xiaozhi.xiaozhi.correct_text', return_value='名称乙') as correction, \
             patch('xiaozhi.xiaozhi.EventManager', events), patch('xiaozhi.xiaozhi.get_env', return_value=True):
            XiaoZhi._handle_stt_message(fake, {'text': '名称甲'})
            schedule.call_args.args[0]()
            fake.set_chat_message.assert_called_with('user', '名称乙')
            correction.reset_mock()
            XiaoZhi._handle_stt_message(fake, {'text': '退出对话'})
            correction.assert_not_called()
            events.on_local_exit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
