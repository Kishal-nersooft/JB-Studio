// Run: node --test bnb_portal_appointment/tests/test_mobile_booking_actions.mjs
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';
const source=readFileSync(new URL('../static/src/js/base.js',import.meta.url),'utf8');
function fixture(id='step-service') {
    const classes=new Set(), events={}, keyboardEvents={};
    let clicks=0, observed=0;
    const original={disabled:false, click:()=>clicks++};
    const step={id,style:{display:'block'},querySelector:()=>original};
    const button={addEventListener:(name,fn)=>events[name]=fn};
    const summary={};
    const bar={querySelector:sel=>sel.includes('Continue')?button:summary};
    const root={children:[step], contains:()=>true};
    const active={matches:()=>true};
    const window={innerHeight:844,visualViewport:{height:844,addEventListener:(name,fn)=>keyboardEvents[name]=fn},bookingMobileActions:bar};
    const errors=[],saved=[];
    const context=vm.createContext({URLSearchParams, window:Object.assign(window,{location:{search:''}}),
        document:{body:{classList:{toggle:(name,on)=>on?classes.add(name):classes.delete(name)}},activeElement:active,addEventListener(){}},
        getComputedStyle:()=>({display:'block'}),setTimeout:fn=>fn(),
        MutationObserver:class {constructor(fn){observed=fn;}observe(){}},
        sessionStorage:{setItem:(...args)=>saved.push(args)},reportBookingError:(...args)=>errors.push(args)});
    const c=vm.createContext({...context,root,bar});
    vm.runInContext(source.slice(source.indexOf('const BookingState ='),source.indexOf('const Utils ='))+source.slice(source.indexOf('class MobileBookingActions {'),source.indexOf('class BookingApp {'))+'\nglobalThis.state=BookingState;globalThis.controller=new MobileBookingActions(root,bar);',c);
    return {c,window,step,original,button,summary,bar,root,classes,events,keyboardEvents,errors,saved,clicks:()=>clicks,observe:()=>observed()};
}
test('Storage save works before initialization despite DOM id exposure on window',()=>{
    const f=fixture();f.c.state.persist();assert.equal(f.saved.length,1);assert.equal(f.errors.length,0);
});
test('Mobile action delegates to existing validation and mirrors disabled guard',()=>{
    const f=fixture();f.events.click();assert.equal(f.clicks(),1);
    f.original.disabled=true;f.observe();assert.equal(f.button.disabled,true);f.events.click();assert.equal(f.clicks(),1);
});
test('State changes update selection summary and payment action',()=>{
    const f=fixture('step-payment');f.window.bnbMobileBookingController=f.c.controller;
    f.c.state.data.selectedServices=[{id:1},{id:2}];f.c.state.persist();
    assert.equal(f.summary.textContent,'2 services selected');assert.equal(f.button.textContent,'Secure checkout');assert.equal(f.errors.length,0);
});
test('Location, confirmation and absent steps hide the action bar',()=>{
    const f=fixture();for(const id of ['step-location','step-confirmation']){f.step.id=id;f.observe();assert.equal(f.bar.hidden,true);}
    f.root.children=[];f.observe();assert.equal(f.bar.hidden,true);
});
test('Keyboard reduces viewport: bar hides while entering text and restores afterward',()=>{
    const f=fixture();f.window.visualViewport.height=500;f.keyboardEvents.resize();assert.ok(f.classes.has('bnb-booking-keyboard-open'));
    f.window.visualViewport.height=844;f.keyboardEvents.resize();assert.ok(!f.classes.has('bnb-booking-keyboard-open'));
});
