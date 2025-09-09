/*
 * SWFUpload jQuery Plugin v1.0.0
 *
 * Copyright (c) 2009 Adam Royle
 * Licensed under the MIT license.
 *
 */

(function(e){var t=["swfupload_preload_handler","swfupload_load_failed_handler","swfupload_loaded_handler","file_dialog_start_handler","file_queued_handler","file_queue_error_handler","file_dialog_complete_handler","upload_resize_start_handler","upload_start_handler","upload_progress_handler","upload_error_handler","upload_success_handler","upload_complete_handler","mouse_click_handler","mouse_out_handler","mouse_over_handler","queue_complete_handler"],n=[];e.fn.swfupload=function(){var r=e.makeArray(arguments);return this.each(function(){var i;if(r.length==1&&typeof r[0]=="object"){i=e(this).data("__swfu");if(!i){var s=r[0],o=e(this),u=[];e.merge(u,t),e.merge(u,n),e.each(u,function(t,n){var r=n.replace(/_handler$/,"").replace(/_([a-z])/g,function(){return arguments[1].toUpperCase()});s[n]=function(){var t=e.Event(r);return o.trigger(t,e.makeArray(arguments)),!t.isDefaultPrevented()}}),e(this).data("__swfu",new SWFUpload(s))}}else if(r.length>0&&typeof r[0]=="string"){var a=r.shift();i=e(this).data("__swfu"),i&&i[a]&&i[a].apply(i,r)}})},e.swfupload={additionalHandlers:function(){if(arguments.length===0)return n.slice();e(arguments).each(function(t,r){e.merge(n,e.makeArray(r))})},defaultHandlers:function(){return t.slice()},getInstance:function(t){return e(t).data("__swfu")}}})(jQuery);