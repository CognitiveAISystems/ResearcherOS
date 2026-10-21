import test from 'node:test';
import assert from 'node:assert/strict';
import {CARD_SKILLS, reportChatCommand} from '../web/chat-skills.js';
test('card menu exposes exactly the four approved commands', () => {
  assert.deepEqual(CARD_SKILLS.map(s => s.command), ['grill-me', 'prose', 'question', 'run']);
});
test('commands preserve the request and use the correct execution mode', () => {
  for (const [command, purpose] of [['grill-me','grill_me'],['grill_me','grill_me'],['prose','prose'],['question','question'],['run','run'],['make_report','make_report']]) {
    assert.deepEqual(reportChatCommand(`/${command} Моя задача\nДетали`), {purpose, question:'Моя задача\nДетали'});
    assert.ok(reportChatCommand(`/${command}`).question);
  }
  for (const text of ['/runner test','/run-other','обычный вопрос']) assert.deepEqual(reportChatCommand(text), {purpose:'agent',question:text});
});
