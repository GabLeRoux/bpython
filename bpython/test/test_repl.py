import collections
from itertools import islice
import os
import socket
import sys

from mock import Mock, MagicMock

try:
    import unittest2 as unittest
except ImportError:
    import unittest

py3 = (sys.version_info[0] == 3)

from bpython import config, repl, cli, autocomplete


def setup_config(conf):
    config_struct = config.Struct()
    config.loadini(config_struct, os.devnull)
    if 'autocomplete_mode' in conf:
        config_struct.autocomplete_mode = conf['autocomplete_mode']
    return config_struct

class FakeHistory(repl.History):

    def __init__(self):
        pass

    def reset(self):
        pass

class FakeRepl(repl.Repl):
    def __init__(self, conf={}):
        repl.Repl.__init__(self, repl.Interpreter(), setup_config(conf))
        self.current_line = ""
        self.cursor_offset = 0

class FakeCliRepl(cli.CLIRepl, FakeRepl):
    def __init__(self):
        self.s = ''
        self.cpos = 0
        self.rl_history = FakeHistory()

class TestMatchesIterator(unittest.TestCase):

    def setUp(self):
        self.matches = ['bobby', 'bobbies', 'bobberina']
        self.matches_iterator = repl.MatchesIterator()
        self.matches_iterator.current_word = 'bob'
        self.matches_iterator.orig_line = 'bob'
        self.matches_iterator.orig_cursor_offset = len('bob')
        self.matches_iterator.matches = self.matches

    def test_next(self):
        self.assertEqual(self.matches_iterator.next(), self.matches[0])

        for x in range(len(self.matches) - 1):
            self.matches_iterator.next()

        self.assertEqual(self.matches_iterator.next(), self.matches[0])
        self.assertEqual(self.matches_iterator.next(), self. matches[1])
        self.assertNotEqual(self.matches_iterator.next(), self.matches[1])

    def test_previous(self):
        self.assertEqual(self.matches_iterator.previous(), self.matches[2])

        for x in range(len(self.matches) - 1):
            self.matches_iterator.previous()

        self.assertNotEqual(self.matches_iterator.previous(), self.matches[0])
        self.assertEqual(self.matches_iterator.previous(), self.matches[1])
        self.assertEqual(self.matches_iterator.previous(), self.matches[0])

    def test_nonzero(self):
        """self.matches_iterator should be False at start,
        then True once we active a match.
        """
        self.assertFalse(self.matches_iterator)
        self.matches_iterator.next()
        self.assertTrue(self.matches_iterator)

    def test_iter(self):
        slice = islice(self.matches_iterator, 0, 9)
        self.assertEqual(list(slice), self.matches * 3)

    def test_current(self):
        self.assertRaises(ValueError, self.matches_iterator.current)
        self.matches_iterator.next()
        self.assertEqual(self.matches_iterator.current(), self.matches[0])

    def test_update(self):
        slice = islice(self.matches_iterator, 0, 3)
        self.assertEqual(list(slice), self.matches)

        newmatches = ['string', 'str', 'set']
        completer = Mock()
        completer.locate.return_value = (0, 1, 's')
        self.matches_iterator.update(1, 's', newmatches, completer)

        newslice = islice(newmatches, 0, 3)
        self.assertNotEqual(list(slice), self.matches)
        self.assertEqual(list(newslice), newmatches)

    def test_cur_line(self):
        completer = Mock()
        completer.locate.return_value = (0,
                self.matches_iterator.orig_cursor_offset,
                self.matches_iterator.orig_line)
        self.matches_iterator.completer = completer

        self.assertRaises(ValueError, self.matches_iterator.cur_line)

        self.assertEqual(self.matches_iterator.next(), self.matches[0])
        self.assertEqual(self.matches_iterator.cur_line(),
                         (len(self.matches[0]), self.matches[0]))

    def test_is_cseq(self):
        self.assertTrue(self.matches_iterator.is_cseq())


class TestArgspec(unittest.TestCase):
    def setUp(self):
        self.repl = FakeRepl()
        self.repl.push("def spam(a, b, c):\n", False)
        self.repl.push("    pass\n", False)
        self.repl.push("\n", False)

    def setInputLine(self, line):
        """Set current input line of the test REPL."""
        self.repl.current_line = line
        self.repl.cursor_offset = len(line)

    def test_func_name(self):
        for (line, expected_name) in [("spam(", "spam"),
                                      ("spam(map([]", "map"),
                                      ("spam((), ", "spam")]:
            self.setInputLine(line)
            self.assertTrue(self.repl.get_args())
            self.assertEqual(self.repl.current_func.__name__, expected_name)

    def test_syntax_error_parens(self):
        for line in ["spam(]", "spam([)", "spam())"]:
            self.setInputLine(line)
            # Should not explode
            self.repl.get_args()

    def test_kw_arg_position(self):
        self.setInputLine("spam(a=0")
        self.assertTrue(self.repl.get_args())
        self.assertEqual(self.repl.argspec[3], "a")

        self.setInputLine("spam(1, b=1")
        self.assertTrue(self.repl.get_args())
        self.assertEqual(self.repl.argspec[3], "b")

        self.setInputLine("spam(1, c=2")
        self.assertTrue(self.repl.get_args())
        self.assertEqual(self.repl.argspec[3], "c")

    def test_lambda_position(self):
        self.setInputLine("spam(lambda a, b: 1, ")
        self.assertTrue(self.repl.get_args())
        self.assertTrue(self.repl.argspec)
        # Argument position
        self.assertEqual(self.repl.argspec[3], 1)

    def test_issue127(self):
        self.setInputLine("x=range(")
        self.assertTrue(self.repl.get_args())
        self.assertEqual(self.repl.current_func.__name__, "range")

        self.setInputLine("{x:range(")
        self.assertTrue(self.repl.get_args())
        self.assertEqual(self.repl.current_func.__name__, "range")

        self.setInputLine("foo(1, 2, x,range(")
        self.assertEqual(self.repl.current_func.__name__, "range")

        self.setInputLine("(x,range(")
        self.assertEqual(self.repl.current_func.__name__, "range")

    def test_nonexistent_name(self):
        self.setInputLine("spamspamspam(")
        self.assertFalse(self.repl.get_args())


class TestGetSource(unittest.TestCase):
    def setUp(self):
        self.repl = FakeRepl()

    def set_input_line(self, line):
        """Set current input line of the test REPL."""
        self.repl.current_line = line
        self.repl.cursor_offset = len(line)

    def assert_get_source_error_for_current_function(self, func, msg):
        self.repl.current_func = func
        self.assertRaises(repl.SourceNotFound, self.repl.get_source_of_current_name)
        try:
            self.repl.get_source_of_current_name()
        except repl.SourceNotFound as e:
            self.assertEqual(e.args[0], msg)

    def test_current_function(self):
        self.set_input_line('INPUTLINE')
        self.repl.current_func = collections.MutableSet.add
        self.assertIn("Add an element.", self.repl.get_source_of_current_name())

        self.assert_get_source_error_for_current_function(
                collections.defaultdict.copy, "No source code found for INPUTLINE")

        self.assert_get_source_error_for_current_function(
                collections.defaultdict, "could not find class definition")

        self.assert_get_source_error_for_current_function(
                [], "No source code found for INPUTLINE")

        self.assert_get_source_error_for_current_function(
                list.pop, "No source code found for INPUTLINE")

    def test_current_line(self):
        self.repl.interp.locals['a'] = socket.socket
        self.set_input_line('a')
        self.assertIn('dup(self)', self.repl.get_source_of_current_name())

#TODO add tests for various failures without using current function


class TestRepl(unittest.TestCase):

    def setInputLine(self, line):
        """Set current input line of the test REPL."""
        self.repl.current_line = line
        self.repl.cursor_offset = len(line)

    def setUp(self):
        self.repl = FakeRepl()

    def test_current_string(self):
        self.setInputLine('a = "2"')
        self.repl.cpos = 0 #TODO factor cpos out of repl.Repl
        self.assertEqual(self.repl.current_string(), '"2"')

        self.setInputLine('a = "2" + 2')
        self.assertEqual(self.repl.current_string(), '')

    def test_push(self):
        self.repl = FakeRepl()
        self.repl.push("foobar = 2")
        self.assertEqual(self.repl.interp.locals['foobar'], 2)

    # COMPLETE TESTS
    # 1. Global tests
    def test_simple_global_complete(self):
        self.repl = FakeRepl({'autocomplete_mode': autocomplete.SIMPLE})
        self.setInputLine("d")

        self.assertTrue(self.repl.complete())
        self.assertTrue(hasattr(self.repl.matches_iter, 'matches'))
        self.assertEqual(self.repl.matches_iter.matches,
            ['def', 'del', 'delattr(', 'dict(', 'dir(', 'divmod('])

    @unittest.skip("disabled while non-simple completion is disabled")
    def test_substring_global_complete(self):
        self.repl = FakeRepl({'autocomplete_mode': autocomplete.SUBSTRING})
        self.setInputLine("time")

        self.assertTrue(self.repl.complete())
        self.assertTrue(hasattr(self.repl.completer,'matches'))
        self.assertEqual(self.repl.completer.matches,
            ['RuntimeError(', 'RuntimeWarning('])

    @unittest.skip("disabled while non-simple completion is disabled")
    def test_fuzzy_global_complete(self):
        self.repl = FakeRepl({'autocomplete_mode': autocomplete.FUZZY})
        self.setInputLine("doc")

        self.assertTrue(self.repl.complete())
        self.assertTrue(hasattr(self.repl.completer,'matches'))
        self.assertEqual(self.repl.completer.matches,
            ['UnboundLocalError(', '__doc__'])

    # 2. Attribute tests
    def test_simple_attribute_complete(self):
        self.repl = FakeRepl({'autocomplete_mode': autocomplete.SIMPLE})
        self.setInputLine("Foo.b")

        code = "class Foo():\n\tdef bar(self):\n\t\tpass\n"
        for line in code.split("\n"):
            self.repl.push(line)

        self.assertTrue(self.repl.complete())
        self.assertTrue(hasattr(self.repl.matches_iter,'matches'))
        self.assertEqual(self.repl.matches_iter.matches,
            ['Foo.bar'])

    @unittest.skip("disabled while non-simple completion is disabled")
    def test_substring_attribute_complete(self):
        self.repl = FakeRepl({'autocomplete_mode': autocomplete.SUBSTRING})
        self.setInputLine("Foo.az")

        code = "class Foo():\n\tdef baz(self):\n\t\tpass\n"
        for line in code.split("\n"):
            self.repl.push(line)

        self.assertTrue(self.repl.complete())
        self.assertTrue(hasattr(self.repl.completer,'matches'))
        self.assertEqual(self.repl.completer.matches,
            ['Foo.baz'])

    @unittest.skip("disabled while non-simple completion is disabled")
    def test_fuzzy_attribute_complete(self):
        self.repl = FakeRepl({'autocomplete_mode': autocomplete.FUZZY})
        self.setInputLine("Foo.br")

        code = "class Foo():\n\tdef bar(self):\n\t\tpass\n"
        for line in code.split("\n"):
            self.repl.push(line)

        self.assertTrue(self.repl.complete())
        self.assertTrue(hasattr(self.repl.completer,'matches'))
        self.assertEqual(self.repl.completer.matches,
            ['Foo.bar'])

    # 3. Edge Cases
    def test_updating_namespace_complete(self):
        self.repl = FakeRepl({'autocomplete_mode': autocomplete.SIMPLE})
        self.setInputLine("foo")
        self.repl.push("foobar = 2")

        self.assertTrue(self.repl.complete())
        self.assertTrue(hasattr(self.repl.matches_iter,'matches'))
        self.assertEqual(self.repl.matches_iter.matches,
            ['foobar'])

    def test_file_should_not_appear_in_complete(self):
        self.repl = FakeRepl({'autocomplete_mode': autocomplete.SIMPLE})
        self.setInputLine("_")
        self.assertTrue(self.repl.complete())
        self.assertTrue(hasattr(self.repl.matches_iter,'matches'))
        self.assertNotIn('__file__', self.repl.matches_iter.matches)


class TestCliRepl(unittest.TestCase):

    def setUp(self):
        self.repl = FakeCliRepl()

    def test_atbol(self):
        self.assertTrue(self.repl.atbol())

        self.repl.s = "\t\t"
        self.assertTrue(self.repl.atbol())

        self.repl.s = "\t\tnot an empty line"
        self.assertFalse(self.repl.atbol())

    def test_addstr(self):
        self.repl.complete = Mock(True)

        self.repl.s = "foo"
        self.repl.addstr("bar")
        self.assertEqual(self.repl.s, "foobar")

        self.repl.cpos = 3
        self.repl.addstr('buzz')
        self.assertEqual(self.repl.s, "foobuzzbar")

class TestCliReplTab(unittest.TestCase):

    def setUp(self):
        self.repl = FakeCliRepl()

    # 3 Types of tab complete
    def test_simple_tab_complete(self):
        self.repl.matches_iter = MagicMock()
        if py3:
            self.repl.matches_iter.__bool__.return_value = False
        else:
            self.repl.matches_iter.__nonzero__.return_value = False
        self.repl.complete = Mock()
        self.repl.print_line = Mock()
        self.repl.matches_iter.is_cseq.return_value = False
        self.repl.show_list = Mock()
        self.repl.argspec = Mock()
        self.repl.matches_iter.cur_line.return_value = (None, "foobar")

        self.repl.s = "foo"
        self.repl.tab()
        self.assertTrue(self.repl.complete.called)
        self.repl.complete.assert_called_with(tab=True)
        self.assertEqual(self.repl.s, "foobar")

    @unittest.skip("disabled while non-simple completion is disabled")
    def test_substring_tab_complete(self):
        self.repl.s = "bar"
        self.repl.config.autocomplete_mode = autocomplete.FUZZY
        self.repl.tab()
        self.assertEqual(self.repl.s, "foobar")
        self.repl.tab()
        self.assertEqual(self.repl.s, "foofoobar")

    @unittest.skip("disabled while non-simple completion is disabled")
    def test_fuzzy_tab_complete(self):
        self.repl.s = "br"
        self.repl.config.autocomplete_mode = autocomplete.FUZZY
        self.repl.tab()
        self.assertEqual(self.repl.s, "foobar")

    # Edge Cases
    def test_normal_tab(self):
        """make sure pressing the tab key will
           still in some cases add a tab"""
        self.repl.s = ""
        self.repl.config = Mock()
        self.repl.config.tab_length = 4
        self.repl.complete = Mock()
        self.repl.print_line = Mock()
        self.repl.tab()
        self.assertEqual(self.repl.s, "    ")

    def test_back_parameter(self):
        self.repl.matches_iter = Mock()
        self.repl.matches_iter.matches = True
        self.repl.matches_iter.previous.return_value = "previtem"
        self.repl.matches_iter.is_cseq.return_value = False
        self.repl.show_list = Mock()
        self.repl.argspec = Mock()
        self.repl.matches_iter.cur_line.return_value = (None, "previtem")
        self.repl.print_line = Mock()
        self.repl.s = "foo"
        self.repl.cpos = 0
        self.repl.tab(back=True)
        self.assertTrue(self.repl.matches_iter.previous.called)
        self.assertTrue(self.repl.s, "previtem")

    # Attribute Tests
    @unittest.skip("disabled while non-simple completion is disabled")
    def test_fuzzy_attribute_tab_complete(self):
        """Test fuzzy attribute with no text"""
        self.repl.s = "Foo."
        self.repl.config.autocomplete_mode = autocomplete.FUZZY

        self.repl.tab()
        self.assertEqual(self.repl.s, "Foo.foobar")

    @unittest.skip("disabled while non-simple completion is disabled")
    def test_fuzzy_attribute_tab_complete2(self):
        """Test fuzzy attribute with some text"""
        self.repl.s = "Foo.br"
        self.repl.config.autocomplete_mode = autocomplete.FUZZY

        self.repl.tab()
        self.assertEqual(self.repl.s, "Foo.foobar")

    # Expand Tests
    def test_simple_expand(self):
        self.repl.s = "f"
        self.cpos = 0
        self.repl.matches_iter = Mock()
        self.repl.matches_iter.is_cseq.return_value = True
        self.repl.matches_iter.substitute_cseq.return_value = (3, "foo")
        self.repl.print_line = Mock()
        self.repl.tab()
        self.assertEqual(self.repl.s, "foo")

    @unittest.skip("disabled while non-simple completion is disabled")
    def test_substring_expand_forward(self):
        self.repl.config.autocomplete_mode = autocomplete.SUBSTRING
        self.repl.s = "ba"
        self.repl.tab()
        self.assertEqual(self.repl.s, "bar")

    @unittest.skip("disabled while non-simple completion is disabled")
    def test_fuzzy_expand(self):
        pass


if __name__ == '__main__':
    unittest.main()
