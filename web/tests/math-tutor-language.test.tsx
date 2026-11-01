import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import React from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {I18nProvider} from "../lib/i18n";
import {translate, normalizeLocale, englishMessages, LOCALE_STORAGE_KEY, LOCALE_CHANGE_EVENT, LOCALE_BOOT_SCRIPT} from "../lib/i18n/messages";
import {readLocale, setLocale, subscribeLocale} from "../lib/i18n/storage";
import LanguagePicker from "../components/common/LanguagePicker";
import TutorWelcome from "../features/math-tutor/components/TutorWelcome";
import ChoiceQuestion from "../features/math-tutor/components/ChoiceQuestion";

test("language preference only accepts Chinese and English", () => {
  assert.equal(normalizeLocale("en"),"en");
  for(const value of ["zh-CN", "en-US", "English", "<script>", null, undefined, {}]) assert.equal(normalizeLocale(value),"zh-CN");
  assert.equal(readLocale(),"zh-CN");
});

test("UI templates preserve inserted user text without translating it", () => {
  assert.equal(translate("en","删除对话：{title}",{title:"设置"}),"Delete chat: 设置");
  assert.equal(translate("zh-CN","删除对话：{title}",{title:"设置"}),"删除对话：设置");
  assert.equal(translate("en","A future unknown UI message"),"A future unknown UI message");
  for(const key of ["constructor","toString","__proto__"]) assert.equal(translate("en",key),key);
  assert.equal(translate("en","x = {x} 的函数读数",{x:0}),"Function values at x = 0");
});

test("all English templates retain the source placeholders", () => {
  const slots=(value:string)=>[...new Set([...value.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)].map(x=>x[1]))].sort();
  for(const [source,english] of Object.entries(englishMessages)) assert.deepEqual(slots(english),slots(source),source);
});

test("language picker has exactly two native-language options in either locale", () => {
  for(const locale of ["zh-CN","en"] as const){
    const html=renderToStaticMarkup(<I18nProvider initialLocale={locale}><LanguagePicker /></I18nProvider>);
    assert.equal((html.match(/<option /g)||[]).length,2);
    assert.match(html,/>中文<\/option>/);assert.match(html,/>English<\/option>/);
    assert.ok(html.includes(locale==="en" ? "Interface language" : "界面语言"));
    assert.match(html,new RegExp(`value="${locale}"[^>]*selected`));
  }
});

test("English tutoring chrome keeps question and answer content intact", () => {
  const html=renderToStaticMarkup(<I18nProvider initialLocale="en"><TutorWelcome disabled={false} onChoose={()=>{}} /><ChoiceQuestion choices={{format:"single_choice",version:"v1",options:[{id:"A",text:"用户答案中文"},{id:"B",text:"2"},{id:"C",text:"3"},{id:"D",text:"4"}]}} busy={false} allowUnsure onSubmit={()=>{}} /></I18nProvider>);
  assert.match(html,/Start math tutoring/);assert.match(html,/Choose an answer/);assert.match(html,/Submit choice/);
  assert.match(html,/Not sure yet/);assert.match(html,/用户答案中文/);assert.match(html,/2x\+3=7/);
});

test("language storage applies immediately, syncs only its key, and cleans up listeners", () => {
  const oldWindow=Object.getOwnPropertyDescriptor(globalThis,"window"),oldDocument=Object.getOwnPropertyDescriptor(globalThis,"document");
  const target=new EventTarget();const values=new Map<string,string>();let blocked=false;
  const localStorage={getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>{if(blocked)throw new Error("blocked");values.set(key,value);}};
  Object.defineProperty(globalThis,"window",{configurable:true,value:Object.assign(target,{localStorage})});
  const document={documentElement:{lang:"zh-CN"}};
  Object.defineProperty(globalThis,"document",{configurable:true,value:document});
  let changes=0;const unsubscribe=subscribeLocale(()=>changes++);
  const storage=(key:string|null)=>{const event=new Event("storage");Object.defineProperty(event,"key",{value:key});target.dispatchEvent(event);};
  try{
    setLocale("en");assert.equal(values.get(LOCALE_STORAGE_KEY),"en");assert.equal(document.documentElement.lang,"en");assert.equal(readLocale(),"en");assert.equal(changes,1);
    storage("some-other-preference");assert.equal(changes,1);
    values.set(LOCALE_STORAGE_KEY,"zh-CN");storage(LOCALE_STORAGE_KEY);assert.equal(readLocale(),"zh-CN");assert.equal(changes,2);
    blocked=true;setLocale("en");assert.equal(readLocale(),"en");assert.equal(document.documentElement.lang,"en");
    blocked=false;setLocale("zh-CN");values.set(LOCALE_STORAGE_KEY,"bad");storage(null);assert.equal(readLocale(),"zh-CN");
    unsubscribe();const before=changes;target.dispatchEvent(new Event(LOCALE_CHANGE_EVENT));assert.equal(changes,before);
  }finally{
    unsubscribe();blocked=false;setLocale("zh-CN");
    if(oldWindow)Object.defineProperty(globalThis,"window",oldWindow);else Reflect.deleteProperty(globalThis,"window");
    if(oldDocument)Object.defineProperty(globalThis,"document",oldDocument);else Reflect.deleteProperty(globalThis,"document");
  }
});

test("pre-hydration script validates locale and handles unavailable storage", () => {
  for(const value of ["en","invalid"]){const document={documentElement:{lang:""}};vm.runInNewContext(LOCALE_BOOT_SCRIPT,{document,localStorage:{getItem:()=>value}});assert.equal(document.documentElement.lang,value==="en"?"en":"zh-CN");}
  const document={documentElement:{lang:"en"}};vm.runInNewContext(LOCALE_BOOT_SCRIPT,{document,localStorage:{getItem:()=>{throw new Error("blocked");}}});assert.equal(document.documentElement.lang,"zh-CN");
});
