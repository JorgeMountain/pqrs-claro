import test from 'node:test';
import assert from 'node:assert/strict';
import {createQueueRefresh} from '../src/pqrs_claro/static/recorrido/queue-refresh.js';
function fixture(){
 let visible=true,work=true,editing=false,callCount=0,next,id=0;const delays=[];
 const refresh=createQueueRefresh({visible:()=>visible,hasWork:()=>work,editing:()=>editing,
  load:async()=>{callCount++;refresh.schedule();},setTimer:(fn,ms)=>{next=fn;delays.push(ms);return ++id;},clearTimer:()=>{next=null;}});
 return {refresh,delays,get calls(){return callCount},set visible(v){visible=v},set work(v){work=v},set editing(v){editing=v},get pending(){return Boolean(next)},async tick(){const fn=next;next=null;if(fn)await fn();}};
}
test('actualiza mientras procesa y detiene consultas al terminar',async()=>{const f=fixture();f.refresh.schedule();assert.equal(f.delays[0],2000);await f.tick();assert.equal(f.calls,1);f.work=false;await f.tick();assert.equal(f.calls,2);assert.equal(f.pending,false);});
test('al salir de bandeja no hace nuevas peticiones',async()=>{const f=fixture();f.refresh.schedule();f.visible=false;await f.tick();assert.equal(f.calls,0);assert.equal(f.pending,false);});
test('no reemplaza una tarjeta o diálogo mientras se interactúa',async()=>{const f=fixture();f.editing=true;f.refresh.schedule();await f.tick();assert.equal(f.calls,0);assert.equal(f.pending,true);f.editing=false;await f.tick();assert.equal(f.calls,1);});
test('reintenta errores con espera creciente limitada y permite cancelar',()=>{const f=fixture();for(let i=0;i<10;i++)f.refresh.schedule(true);assert.equal(f.delays[0],4000);assert.equal(f.delays.at(-1),30000);f.refresh.stop();assert.equal(f.pending,false);});
test('no consulta periódicamente una bandeja sin trabajos',()=>{const f=fixture();f.work=false;f.refresh.schedule();assert.equal(f.pending,false);f.refresh.schedule(true);assert.equal(f.pending,true);});
