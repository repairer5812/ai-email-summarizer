/*
 * jQuery Progress Bar plugin
 * Version 2.0 (06/22/2009)
 * @requires jQuery v1.2.1 or later
 *
 * Copyright (c) 2008 Gary Teo
 * http://t.wits.sg

USAGE:
	$(".someclass").progressBar();
	$("#progressbar").progressBar();
	$("#progressbar").progressBar(45);							// percentage
	$("#progressbar").progressBar({showText: false });			// percentage with config
	$("#progressbar").progressBar(45, {showText: false });		// percentage with config
*/

(function(e){e.extend({progressBar:new function(){this.defaults={steps:20,stepDuration:20,max:100,showText:!0,textFormat:"percentage",width:120,height:12,callback:null,boxImage:"images/progressbar.gif",barImage:{0:"images/progressbg_red.gif",30:"images/progressbg_orange.gif",70:"images/progressbg_green.gif"},running_value:0,value:0,image:null},this.construct=function(t,n){var r=null,i=null;return t!=null&&(isNaN(t)?i=t:(r=t,n!=null&&(i=n))),this.each(function(t){function p(e){return e.running_value*100/e.max}function d(e){var t=e.barImage;if(typeof e.barImage=="object")for(var n in e.barImage){if(!(e.running_value>=parseInt(n)))break;t=e.barImage[n]}return t}function v(e){if(e.showText){if(e.textFormat=="percentage")return" "+Math.round(e.running_value)+"%";if(e.textFormat=="fraction")return" "+e.running_value+"/"+e.max}}var n=this,s=this.config;if(r!=null&&this.bar!=null&&this.config!=null)this.config.value=parseInt(r),i!=null&&(n.config=e.extend(this.config,i)),s=n.config;else{var o=e(this),s=e.extend({},e.progressBar.defaults,i);s.id=o.attr("id")?o.attr("id"):Math.ceil(Math.random()*1e5),r==null&&(r=o.html().replace("%","")),s.value=parseInt(r),s.running_value=0,s.image=d(s);var u=["steps","stepDuration","max","width","height","running_value","value"];for(var a=0;a<u.length;a++)s[u[a]]=parseInt(s[u[a]]);o.html("");var f=document.createElement("img"),l=document.createElement("span"),c=e(f),h=e(l);n.bar=c,c.attr("id",s.id+"_pbImage"),h.attr("id",s.id+"_pbText"),h.html(v(s)),c.attr("title",v(s)),c.attr("alt",v(s)),c.attr("src",s.boxImage),c.attr("width",s.width),c.css("width",s.width+"px"),c.css("height",s.height+"px"),c.css("background-image","url("+s.image+")"),c.css("background-position",s.width*-1+"px 50%"),c.css("padding","0"),c.css("margin","0"),o.append(c),o.append(h)}s.increment=Math.round((s.value-s.running_value)/s.steps),s.increment<0&&(s.increment*=-1),s.increment<1&&(s.increment=1);var m=setInterval(function(){var t=s.width/100;s.running_value>s.value?s.running_value-s.increment<s.value?s.running_value=s.value:s.running_value-=s.increment:s.running_value<s.value&&(s.running_value+s.increment>s.value?s.running_value=s.value:s.running_value+=s.increment),s.running_value==s.value&&clearInterval(m);var r=e("#"+s.id+"_pbImage"),i=e("#"+s.id+"_pbText"),o=d(s);o!=s.image&&(r.css("background-image","url("+o+")"),s.image=o),r.css("background-position",s.width*-1+p(s)*t+"px 50%"),r.attr("title",v(s)),i.html(v(s)),s.callback!=null&&typeof s.callback=="function"&&s.callback(s),n.config=s},s.stepDuration)})}}}),e.fn.extend({progressBar:e.progressBar.construct})})(jQuery);