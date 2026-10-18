// Runs in Adobe InDesign. Always works on a hidden copy and closes only that copy.
(function () {
    function quote(value) { return '"' + String(value).replace(/\\/g,'\\\\').replace(/"/g,'\\"').replace(/\r/g,'\\r').replace(/\n/g,'\\n').replace(/\t/g,'\\t') + '"'; }
    function json(value) {
        if (value === null) return 'null';
        if (typeof value === 'string') return quote(value);
        if (typeof value === 'number' || typeof value === 'boolean') return String(value);
        var parts=[],key;
        if (value instanceof Array) { for(var i=0;i<value.length;i++)parts.push(json(value[i]));return '['+parts.join(',')+']'; }
        for(key in value)if(value.hasOwnProperty(key))parts.push(quote(key)+':'+json(value[key]));return '{'+parts.join(',')+'}';
    }
    function framesOf(document) {
        var result=[], items=document.allPageItems;
        for(var i=0;i<items.length;i++) {
            var kind=items[i].constructor.name;
            if ((kind==='Rectangle'||kind==='Oval'||kind==='Polygon') && items[i].parentPage) result.push(items[i]);
        }
        return result;
    }
    var document=null,result={ok:false},oldInteraction=app.scriptPreferences.userInteractionLevel;
    try {
        app.scriptPreferences.userInteractionLevel=UserInteractionLevels.NEVER_INTERACT;
        document=app.open(File(request.template),false,OpenOptions.OPEN_COPY);
        var frames=framesOf(document),i;
        if(request.operation==='inspect') {
            result.frames=[];
            for(i=0;i<frames.length;i++)result.frames.push({key:String(i),label:frames[i].label||frames[i].name||'',page:frames[i].parentPage.name});
        } else {
            for(var key in request.mapping)if(request.mapping.hasOwnProperty(key)) {
                var frame=frames[Number(key)],drawing=request.drawings[request.mapping[key]];
                if(!frame||!drawing)throw Error('The template frames changed; import the template again.');
                var layerLocked=frame.itemLayer.locked,frameLocked=frame.locked;
                frame.itemLayer.locked=false;frame.locked=false;
                while(frame.allGraphics.length)frame.allGraphics[0].remove();
                var placed=frame.place(File(drawing));
                frame.fit(request.fit==='cover'?FitOptions.FILL_PROPORTIONALLY:FitOptions.PROPORTIONALLY);
                frame.fit(FitOptions.CENTER_CONTENT);
                for(i=0;i<placed.length;i++)if(placed[i].itemLink&&placed[i].itemLink.isValid)placed[i].itemLink.unlink();
                frame.locked=frameLocked;frame.itemLayer.locked=layerLocked;
            }
            var items=document.allPageItems;
            for(i=0;i<items.length;i++)if(items[i].constructor.name==='TextFrame') {
                var label=String(items[i].label||'').toLowerCase();
                if(label==='morphaic:title')items[i].contents=request.title;
                if(label==='morphaic:seed')items[i].contents=String(request.seed);
            }
            document.save(File(request.output+'/morphaic-layout.indd'));
            document.exportFile(ExportFormat.INDESIGN_MARKUP,File(request.output+'/morphaic-layout.idml'),false);
            document.exportFile(ExportFormat.PDF_TYPE,File(request.output+'/morphaic-layout.pdf'),false);
        }
        result.ok=true;
    } catch(error) { result.error=String(error.message||error); }
    finally {
        if(document&&document.isValid)document.close(SaveOptions.NO);
        app.scriptPreferences.userInteractionLevel=oldInteraction;
        var file=File(request.result);file.encoding='UTF-8';file.open('w');file.write(json(result));file.close();
    }
})();
