function readPreference(key){try{return localStorage.getItem(key);}catch{return null;}}
function writePreference(key,value){try{localStorage.setItem(key,value);}catch{}}
const itemCache=new WeakMap();let commitCache=null;let searchTimer;let filterCache=null;const expandedChanges=new Set();const changeIds=new Map();function changeIdentity(item,commit){const prepared=prepareItem(item,commit);if(!prepared.changeId){const key=JSON.stringify([commit.sha,item.source,item.type,item.link,item.relatedLink]);if(!changeIds.has(key))changeIds.set(key,String(changeIds.size+1));prepared.changeId=changeIds.get(key);}
return prepared.changeId;}
function renderPreviousLink(item,commit){const prepared=prepareItem(item,commit);if(!('previousHtml'in prepared)){prepared.previousHtml=renderLinkContent(String(item.relatedLink).replace(/^\*\s*/,''));}
return prepared.previousHtml;}
function getFilterView(){const allRows=getRows();const query=state.searchQuery.trim().toLowerCase();const key=JSON.stringify([query,state.currentFilter,state.categoryFilter,state.showOnlyStarred]);if(filterCache?.source===allRows&&filterCache.key===key)return filterCache;const rows=[];const typeCounts={new:0,updated:0,removed:0};const categoryCounts=Object.create(null);const categories=new Set();for(const row of allRows){const prepared=prepareItem(row.item,row.commit);categories.add(prepared.source);if((state.showOnlyStarred&&!prepared.starred)||(query&&!prepared.text.includes(query)))continue;const typeMatches=state.currentFilter==='all'||row.type===state.currentFilter;const categoryMatches=state.categoryFilter==='all'||prepared.source===state.categoryFilter;if(categoryMatches&&row.type in typeCounts)typeCounts[row.type]++;if(typeMatches)categoryCounts[prepared.source]=(categoryCounts[prepared.source]||0)+1;if(typeMatches&&categoryMatches)rows.push(row);}
filterCache={source:allRows,key,rows,typeCounts,categoryCounts,categories:[...categories].sort()};return filterCache;}
function prepareItem(item,commit){let prepared=itemCache.get(item);if(!prepared){prepared={text:`${item.link ?? ""} ${item.relatedLink ?? ""} ${item.source ?? ""} ${commit.message ?? ""}`.toLowerCase(),source:String(item.source??"").toLowerCase(),starred:String(item.link??"").includes("⭐"),};itemCache.set(item,prepared);}
return prepared;}
function renderCachedLink(item,commit,removed=false){const prepared=prepareItem(item,commit);const key=removed?"removedHtml":"html";if(!(key in prepared)){prepared[key]=renderLinkContent(String(item.link??"").replace(/^\*\s*/,""),{strikeMain:removed},);}
return prepared[key];}
function getRows(){const commits=getAllCommits();if(commitCache.rows)return commitCache.rows;commitCache.rows=commits.flatMap((commit)=>[...dedupeLinks(commit.added).map((item)=>({item,commit,type:item.type||"new",})),...dedupeLinks(commit.removed).map((item)=>({item,commit,type:"removed",})),]);return commitCache.rows;}
function matchingRows({ignoreType=false,ignoreCategory=false}={}){if(!ignoreType&&!ignoreCategory)return getFilterView().rows;const query=state.searchQuery.trim().toLowerCase();return getRows().filter(({item,commit,type})=>{const prepared=prepareItem(item,commit);return((!state.showOnlyStarred||prepared.starred)&&(ignoreType||state.currentFilter==="all"||type===state.currentFilter)&&(ignoreCategory||state.categoryFilter==="all"||prepared.source===state.categoryFilter)&&(!query||prepared.text.includes(query)));});}
const state={currentFilter:"all",showOnlyStarred:readPreference("fmhy-show-starred")==="true",currentPage:1,itemsPerPage:50,searchQuery:"",categoryFilter:"all",theme:readPreference("fmhy-theme")||"auto",categoryFiltersExpanded:false,showMonthly:false,monthlyData:null,monthlyLoading:false,};function updateUrl(){const params=new URLSearchParams();if(state.searchQuery)params.set("q",state.searchQuery);if(state.currentFilter!=="all")params.set("filter",state.currentFilter);if(state.categoryFilter!=="all")params.set("cat",state.categoryFilter);params.set("starred",state.showOnlyStarred?"1":"0");if(state.showMonthly)params.set("history","1");if(state.currentPage>1)params.set("page",String(state.currentPage));const query=params.toString();const newUrl=query?`${window.location.pathname}?${query}`:window.location.pathname;window.history.replaceState(null,"",newUrl);}
function restoreStateFromUrl(){const params=new URLSearchParams(window.location.search);const q=params.get("q");if(q)state.searchQuery=q;const filter=params.get("filter");if(["new","updated","removed"].includes(filter)){state.currentFilter=filter;}
const cat=params.get("cat");if(cat)state.categoryFilter=cat.toLowerCase();if(params.has("starred"))
state.showOnlyStarred=params.get("starred")==="1";const page=Number(params.get("page"));if(Number.isSafeInteger(page)&&page>0)state.currentPage=page;}
function syncStarToggleUI(){const starBtn=document.getElementById("star-toggle");if(starBtn){starBtn.classList.toggle("active",state.showOnlyStarred);starBtn.setAttribute("aria-pressed",String(state.showOnlyStarred));}}
function escapeHtml(value){return String(value??"").replace(/[&<>"']/g,(char)=>{const entities={"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;",};return entities[char];});}
function escapeAttribute(value){return escapeHtml(value).replace(/`/g,"&#96;");}
function sanitizeUrl(url){const rawUrl=String(url??"").trim();try{const parsed=new URL(rawUrl,window.location.href);if(["http:","https:","mailto:"].includes(parsed.protocol)){return parsed.href;}}catch(e){}
return"";}
function renderBoldText(text){return escapeHtml(text).replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>");}
function renderTextWithBold(text,state){const chunks=String(text??"").split("**");let out="";for(let i=0;i<chunks.length;i++){out+=escapeHtml(chunks[i]);if(i<chunks.length-1){out+=state.boldOpen?"</strong>":"<strong>";state.boldOpen=!state.boldOpen;}}
return out;}
function renderLink(label,url){const safeUrl=sanitizeUrl(url);const safeLabel=renderBoldText(label);if(!safeUrl){return safeLabel;}
return`<a href="${escapeAttribute(safeUrl)}" target="_blank" rel="noopener noreferrer">${safeLabel}</a>`;}
function getAllCommits(){if(!window.fmhyData)return[];const monthly=state.showMonthly?state.monthlyData:null;if(commitCache?.recent===window.fmhyData&&commitCache.monthly===monthly){return commitCache.commits;}
const bySha=new Map(window.fmhyData.commits.map((c)=>[c.sha,c]));for(const commit of monthly?.commits||[]){if(!bySha.has(commit.sha))bySha.set(commit.sha,commit);}
const commits=[...bySha.values()].sort((a,b)=>Date.parse(b.date)-Date.parse(a.date),);commitCache={recent:window.fmhyData,monthly,commits};return commits;}
function getEffectiveTheme(){if(state.theme==="auto"){return window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";}
return state.theme;}
function initTheme(){document.documentElement.setAttribute("data-theme",getEffectiveTheme());updateThemeLabel();const themeSelect=document.getElementById("theme-select");if(themeSelect){themeSelect.value=state.theme;}
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change",()=>{if(state.theme==="auto"){document.documentElement.setAttribute("data-theme",getEffectiveTheme(),);}});}
function setTheme(value){state.theme=value;document.documentElement.setAttribute("data-theme",getEffectiveTheme());writePreference("fmhy-theme",state.theme);updateThemeLabel();}
function updateThemeLabel(){const themeLabel=document.getElementById("theme-label");if(themeLabel){if(state.theme==="auto"){themeLabel.textContent="Auto";}else{themeLabel.textContent=state.theme.charAt(0).toUpperCase()+state.theme.slice(1);}}}
function toggleCategoryFilters(){state.categoryFiltersExpanded=!state.categoryFiltersExpanded;const container=document.getElementById("category-filters");const wrapper=document.getElementById("category-filters-wrapper");const header=document.querySelector(".category-filter-header");const icon=document.getElementById("category-toggle-icon");const text=document.getElementById("category-toggle-text");if(container){container.classList.toggle("collapsed",!state.categoryFiltersExpanded);if(!state.categoryFiltersExpanded){container.style.maxHeight="";}else{container.style.maxHeight=container.scrollHeight+"px";}}
if(wrapper){wrapper.classList.toggle("expanded",state.categoryFiltersExpanded);}
if(header){header.classList.toggle("expanded",state.categoryFiltersExpanded);}
if(icon){icon.classList.toggle("expanded",state.categoryFiltersExpanded);}
document.getElementById("category-toggle-btn")?.setAttribute("aria-expanded",String(state.categoryFiltersExpanded));if(text){text.textContent=state.categoryFiltersExpanded?"Show Less":"Show More";}}
function parseMarkdownLinks(text){const rawText=String(text??"");const marker=rawText.match(/^(⭐|🌟)\s*/u);let processedText=rawText.replace(/^(?:⭐|🌟)\s*/u,"");processedText=processedText.replace(/ \//g," |");const parts=[];const boldState={boldOpen:false};const linkPattern=/(\*\*)?\[([^\]]+)\]\(([^)]+)\)(\*\*)?/g;let lastIndex=0;let match;while((match=linkPattern.exec(processedText))!==null){parts.push(renderTextWithBold(processedText.slice(lastIndex,match.index),boldState,),);const label=match[1]&&match[4]?`**${match[2]}**`:match[2];parts.push(renderLink(label,match[3]));lastIndex=match.index+match[0].length;}
parts.push(renderTextWithBold(processedText.slice(lastIndex),boldState));if(boldState.boldOpen){parts.push("</strong>");}
processedText=parts.join("");if(marker){const label=marker[1]==="⭐"?"Starred source":"Featured source";const markerIcon=`<svg class="resource-marker" role="img" aria-label="${label}" viewBox="0 0 24 24" focusable="false"><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9L12 3Z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>`;return`${markerIcon} ${processedText}`;}
return processedText;}
function renderLinkContent(text,{strikeMain=false}={}){const raw=String(text??"");const linkPattern=/\[[^\]]+\]\([^)]+\)/g;const linkRanges=[];let match;while((match=linkPattern.exec(raw))!==null){linkRanges.push([match.index,match.index+match[0].length]);}
const insideLink=(index)=>linkRanges.some(([start,end])=>index>=start&&index<end);const segments=[];let current="";let boldOpen=false;for(let i=0;i<raw.length;i++){if(raw[i]==="*"&&raw[i+1]==="*"){boldOpen=!boldOpen;current+="**";i++;continue;}
const ch=raw[i];const isSeparator=(ch==="/"||ch==="|")&&raw[i-1]===" "&&!boldOpen&&!insideLink(i);if(isSeparator){segments.push(current);current="";if(raw[i+1]===" ")i++;continue;}
current+=ch;}
segments.push(current);const cleaned=segments.map((segment)=>segment.trim()).filter((segment)=>segment.length>0);const main=cleaned.shift()??"";let html=parseMarkdownLinks(main);if(strikeMain){html=`<span class="removed-text">${html}</span>`;}
const chips=cleaned.map((segment)=>`<span class="link-tag">${parseMarkdownLinks(segment)}</span>`,).join("");if(chips){html+=` <span class="link-tags">${chips}</span>`;}
return html;}
function formatRelativeTime(dateString){const date=new Date(dateString);const now=new Date();const diffMs=now-date;const diffDays=Math.floor(diffMs/(1000*60*60*24));const diffHours=Math.floor((diffMs%(1000*60*60*24))/(1000*60*60),);const diffMinutes=Math.floor((diffMs%(1000*60*60))/(1000*60));if(diffDays>0){return`${diffDays}d ${diffHours}h ago`;}else if(diffHours>0){return`${diffHours}h ${diffMinutes}m ago`;}else{return`${diffMinutes}m ago`;}}
const fullDateFormatter=new Intl.DateTimeFormat('en-US',{weekday:'long',year:'numeric',month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',});const commitDateFormatter=new Intl.DateTimeFormat('en-US',{year:'numeric',month:'short',day:'numeric',});const monthFormatter=new Intl.DateTimeFormat('en-US',{month:'long',year:'numeric',timeZone:'UTC',});function formatFullDate(dateString){return fullDateFormatter.format(new Date(dateString));}
function formatCommitDate(dateString){return commitDateFormatter.format(new Date(dateString));}
async function loadMonthlyCommits(){if(state.monthlyData)return state.monthlyData;const response=await fetch("monthly_commits.json",{cache:"no-cache",signal:AbortSignal.timeout(15000),});if(!response.ok)throw new Error("History could not be loaded");const data=await response.json();if(!/^\d{4}-\d{2}$/.test(data.month)||!Array.isArray(data.commits)||data.commits.some((c)=>!c.sha||!Array.isArray(c.added)||!Array.isArray(c.removed),)){throw new Error("History data is invalid");}
return data;}
function updateMonthlyToggleUI(){const wrapper=document.getElementById("monthly-toggle-wrapper");const spinner=document.getElementById("monthly-loading-spinner");const count=document.getElementById("monthly-count");if(wrapper){wrapper.classList.toggle("loading",state.monthlyLoading);wrapper.setAttribute("aria-busy",String(state.monthlyLoading));}
const toggle=document.getElementById("monthly-toggle");if(toggle)toggle.disabled=state.monthlyLoading;const retry=document.getElementById("monthly-retry");if(retry)retry.disabled=state.monthlyLoading;const label=document.querySelector(".monthly-toggle-text");const month=state.monthlyData?.month||window.fmhyData?.archiveMonth;if(label)label.textContent='Historical';if(toggle)toggle.setAttribute('aria-label',month?`Include ${formatMonth(month)} history`:'Include month history');if(spinner){spinner.style.display=state.monthlyLoading?"inline-block":"none";}
if(count&&state.monthlyData){count.textContent=`(${state.monthlyData.totalCommits})`;count.style.display="inline";}else if(count){count.style.display="none";}}
function showMonthlyMessage(text){const message=document.getElementById("monthly-message");if(message){message.textContent=text;message.classList.remove("hidden");}}
function formatMonth(month){return monthFormatter.format(new Date(`${month}-01T12:00:00Z`));}
async function toggleMonthlyView({restorePage=null}={}){const toggle=document.getElementById("monthly-toggle");if(state.monthlyLoading)return;const startingFilters=getFilterView().key;const startingPage=state.currentPage;const message=document.getElementById("monthly-message");const retry=document.getElementById("monthly-retry");message?.classList.add("hidden");if(retry)retry.hidden=true;if(toggle?.checked){state.monthlyLoading=true;showMonthlyMessage('Loading history… Recent changes are still available.');updateMonthlyToggleUI();try{state.monthlyData=await loadMonthlyCommits();state.showMonthly=true;showMonthlyMessage(`Showing ${formatMonth(state.monthlyData.month)} history plus recent changes.`,);}catch{toggle.checked=false;state.showMonthly=false;showMonthlyMessage("Could not load month history. Please try again.");if(retry)retry.hidden=false;}finally{state.monthlyLoading=false;updateMonthlyToggleUI();}}else{state.showMonthly=false;updateMonthlyToggleUI();}
state.currentPage=state.showMonthly&&restorePage&&startingFilters===getFilterView().key&&startingPage===state.currentPage?restorePage:1;renderCommits();}
function dedupeLinks(links){const seen=new Set();return links.filter((item)=>{const key=`${item.source ?? ""}\u0000${item.link ?? ""}`;if(seen.has(key))return false;seen.add(key);return true;});}
function renderCommit(commit){const filteredAdded=commit.added;const filteredRemoved=commit.removed;if(filteredAdded.length===0&&filteredRemoved.length===0){return"";}
let commitMessage=String(commit.message??"");if(commitMessage.indexOf("\n")!==-1){commitMessage=commitMessage.split("\n")[0];}
const isHistorical=commit.isHistorical===true;const isMonthlyHistorical=commit.isMonthlyHistorical===true;const historicalClass=isHistorical?"historical-commit":"";const monthlyHistoricalClass=isMonthlyHistorical?"monthly-historical":"";const commitSha=String(commit.sha??"");const commitUrl=commitSha?`https://github.com/fmhy/edit/commit/${encodeURIComponent(commitSha)}`:"";const addedHtml=filteredAdded.length>0?`
    <div class="links">
      <ul class="link-list">
        ${filteredAdded
          .map((item) => {
            const linkType = item.type || "new";
            const typeClass =
              linkType === "new"
                ? "new-link"
                : linkType === "updated"
                  ? "updated-link"
                  : "";
            const badge =
              linkType === "new"
                ? '<span class="link-badge new-badge">New</span>'
                : linkType === "updated"
                  ? '<span class="link-badge updated-badge">Updated</span>'
                  : "";
            const query = state.searchQuery.trim().toLowerCase();
            const previousLinkMatches =
              query && String(item.relatedLink ?? "").toLowerCase().includes(query);
            return `<li class="link added-link ${typeClass}"><div class="resource-meta"><span class="source-badge">${escapeHtml(item.source,)}</span>${badge}</div><div class="resource-content">${renderCachedLink(item,commit)}</div>${item.type==="updated"&&item.relatedLink?`<details class="change-details" data-change-id="${escapeAttribute(changeIdentity(item, commit))}" ${expandedChanges.has(changeIdentity(item, commit)) || previousLinkMatches ? 'open' : ''}><summary>What changed?</summary><div class="change-before"><strong>Before</strong> ${renderPreviousLink(item, commit)}</div><div><strong>After</strong> ${renderCachedLink(item, commit)}</div></details>`:""}</li>`;
          })
          .join("")}
      </ul>
    </div>
  `:"";const removedHtml=filteredRemoved.length>0?`
    <div class="links">
      <ul class="link-list">
        ${filteredRemoved
          .map((item) => {
            return `<li class="link removed-link"><div class="resource-meta"><span class="source-badge">${escapeHtml(item.source,)}</span><span class="link-badge removed-badge">Removed</span></div><div class="resource-content">${renderCachedLink(item,commit,true)}</div></li>`;
          })
          .join("")}
      </ul>
    </div>
  `:"";const shaLink=commitUrl?`<a class="commit-sha-text" href="${escapeAttribute(commitUrl)}" target="_blank" rel="noopener noreferrer" aria-label="View commit ${escapeAttribute(commitSha.substring(0, 8))} on GitHub">${escapeHtml(commitSha.substring(0, 8))} ↗</a>`:'';return`
    <section class="commit ${historicalClass} ${monthlyHistoricalClass}">
      <div class="commit-header">
        <h3 class="commit-date"><time datetime="${escapeAttribute(commit.date)}" title="${escapeAttribute(formatFullDate(commit.date))}">${escapeHtml(formatCommitDate(commit.date))}</time></h3>
        <span class="commit-sha">${shaLink}</span>
        <span class="commit-message">${escapeHtml(commitMessage)}</span>
      </div>
      ${addedHtml}
      ${removedHtml}
    </section>`;}
function renderPagination(totalItems){const totalPages=Math.ceil(totalItems/state.itemsPerPage);if(totalPages<=1)return'';const pages=[...new Set([1,state.currentPage-1,state.currentPage,state.currentPage+1,totalPages])].filter(page=>page>=1&&page<=totalPages).sort((a,b)=>a-b);let previous=0;const numbers=pages.map(page=>{const gap=previous&&page-previous>1?'<span class="page-gap" aria-hidden="true">…</span>':'';previous=page;return`${gap}<button type="button" class="page-btn page-number" data-page="${page}" aria-label="Page ${page}" ${page === state.currentPage ? 'aria-current="page"' : ''}>${page}</button>`;}).join('');return`<nav class="pagination" aria-label="Results pages">
    <div class="page-navigation">
      <button type="button" class="page-btn" data-page="${state.currentPage - 1}" ${state.currentPage === 1 ? 'disabled' : ''}>← Previous</button>
      <div class="page-numbers">${numbers}</div>
      <button type="button" class="page-btn" data-page="${state.currentPage + 1}" ${state.currentPage === totalPages ? 'disabled' : ''}>Next →</button>
    </div>
    <form class="page-jump">
      <span class="page-info">Page ${state.currentPage} of ${totalPages}</span>
      <label for="page-input">Go to</label>
      <input id="page-input" name="page" type="number" inputmode="numeric" min="1" max="${totalPages}" value="${state.currentPage}" required aria-label="Page number">
      <button class="page-btn" type="submit">Go</button>
    </form>
  </nav>`;}
function goToPage(page){const totalPages=Math.max(1,Math.ceil(matchingRows().length/state.itemsPerPage));if(!Number.isSafeInteger(page))return;state.currentPage=Math.max(1,Math.min(totalPages,page));renderCommits();const container=document.getElementById('commits-container');if(container){container.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});container.focus({preventScroll:true});}}
function changePage(delta){goToPage(state.currentPage+delta);}
function renderCategoryFilters(){const{categoryCounts:counts,categories}=getFilterView();const total=Object.values(counts).reduce((a,b)=>a+b,0);const container=document.getElementById("category-filters");if(container){const markup=["all",...categories].map((cat)=>`<button type="button"
      class="category-btn ${state.categoryFilter === cat ? "active" : ""}"
      data-category="${escapeAttribute(cat)}" aria-pressed="${state.categoryFilter === cat}">
      ${cat === "all" ? "All Categories" : escapeHtml(cat.replaceAll("-", " "))}
      <span class="category-count">${cat === "all" ? total : counts[cat] || 0}</span></button>`,).join("");if(container.dataset.markup!==markup){container.innerHTML=markup;container.dataset.markup=markup;}}
const select=document.getElementById("category-select");if(select){const markup=["all",...categories].map((cat)=>`<option value="${escapeAttribute(cat)}">${cat === "all" ? "All categories" : escapeHtml(cat.replaceAll("-", " "))} (${cat === "all" ? total : counts[cat] || 0})</option>`,).join("");if(select.dataset.markup!==markup){select.innerHTML=markup;select.dataset.markup=markup;}
select.value=state.categoryFilter;}
if(state.categoryFiltersExpanded&&container)
container.style.maxHeight=`${container.scrollHeight}px`;}
function setCategoryFilter(category){state.categoryFilter=category;state.currentPage=1;document.querySelectorAll(".category-btn").forEach((btn)=>{const active=btn.dataset.category===category;btn.classList.toggle("active",active);btn.setAttribute("aria-pressed",String(active));});renderCommits();}
function setFilter(filter){if(filter!=="all"&&state.currentFilter===filter){filter="all";}
state.currentFilter=filter;state.currentPage=1;document.querySelectorAll(".stat-filter[data-filter]").forEach((btn)=>{const active=btn.dataset.filter===filter;btn.classList.toggle("active",active);btn.setAttribute("aria-pressed",String(active));});renderCommits();}
function updateSearchClear(){const clearBtn=document.getElementById("search-clear");if(clearBtn){clearBtn.hidden=state.searchQuery.length===0;}}
function handleSearch(event){state.searchQuery=event.target.value;state.currentPage=1;updateSearchClear();clearTimeout(searchTimer);searchTimer=setTimeout(()=>{renderCommits();},120);}
function clearSearch(){const input=document.getElementById("search-input");if(input){input.value="";input.focus();}
state.searchQuery="";state.currentPage=1;updateSearchClear();renderCommits();}
function toggleStarFilter(){state.showOnlyStarred=!state.showOnlyStarred;state.currentPage=1;writePreference("fmhy-show-starred",state.showOnlyStarred);syncStarToggleUI();renderCommits();}
function updateSummaryStats(){const counts=getFilterView().typeCounts;for(const type of["all","new","updated","removed"]){const el=document.getElementById(`total-${type}`);if(el)
el.textContent=type==="all"?counts.new+counts.updated+counts.removed:counts[type];}}
function renderCommits({syncUrl=true}={}){clearTimeout(searchTimer);const container=document.getElementById("commits-container");if(!container||!window.fmhyData)return;const focusedCategory=document.activeElement?.dataset?.category;updateSummaryStats();renderCategoryFilters();if(focusedCategory){[...document.querySelectorAll(".category-btn")].find((button)=>button.dataset.category===focusedCategory)?.focus({preventScroll:true});}
const rows=matchingRows();const totalPages=Math.max(1,Math.ceil(rows.length/state.itemsPerPage));state.currentPage=Math.min(Math.max(1,state.currentPage),totalPages);const start=(state.currentPage-1)*state.itemsPerPage;const pageRows=rows.slice(start,start+state.itemsPerPage);const commits=new Map();for(const{item,commit,type}of pageRows){if(!commits.has(commit.sha))
commits.set(commit.sha,{...commit,added:[],removed:[]});commits.get(commit.sha)
[type==="removed"?"removed":"added"].push(item);}
container.querySelectorAll?.('details[data-change-id]').forEach(details=>{if(details.open)expandedChanges.add(details.dataset.changeId);else expandedChanges.delete(details.dataset.changeId);});let html="";let currentGroup=null;for(const commit of commits.values()){const group=state.showMonthly?formatMonth(commit.date.slice(0,7)):null;if(group&&group!==currentGroup){html+=`<div class="date-group-divider"><span class="divider-line"></span><span class="divider-text">${escapeHtml(group)}</span><span class="divider-line"></span></div>`;currentGroup=group;}
html+=renderCommit(commit);}
container.innerHTML=html?html+renderPagination(rows.length):'<div class="no-changes">No matching changes found. Try removing a filter or changing your search.</div>';highlightSearchMatches(container);if(syncUrl)updateUrl();}
function highlightSearchMatches(container){const query=state.searchQuery.trim();if(!query)return;const needle=query.toLowerCase();const walker=document.createTreeWalker(container,NodeFilter.SHOW_TEXT,{acceptNode(node){if(!node.nodeValue||!node.nodeValue.toLowerCase().includes(needle)){return NodeFilter.FILTER_REJECT;}
const parent=node.parentNode;if(parent&&parent.nodeName==="MARK")return NodeFilter.FILTER_REJECT;return NodeFilter.FILTER_ACCEPT;},});const targets=[];let current;while((current=walker.nextNode())){targets.push(current);}
for(const node of targets){const text=node.nodeValue;const lower=text.toLowerCase();const frag=document.createDocumentFragment();let index=0;let found;while((found=lower.indexOf(needle,index))!==-1){if(found>index){frag.appendChild(document.createTextNode(text.slice(index,found)));}
const mark=document.createElement("mark");mark.textContent=text.slice(found,found+needle.length);frag.appendChild(mark);index=found+needle.length;}
if(index<text.length){frag.appendChild(document.createTextNode(text.slice(index)));}
node.parentNode.replaceChild(frag,node);}}
function refreshRelativeTimes(){const data=window.fmhyData;if(!data)return;const lastUpdatedEl=document.getElementById("last-updated");if(lastUpdatedEl&&data.lastUpdated){lastUpdatedEl.textContent=formatRelativeTime(data.lastUpdated);lastUpdatedEl.title=formatFullDate(data.lastUpdated);}
const buildTimeEl=document.getElementById("build-time");if(buildTimeEl&&data.buildTime){buildTimeEl.textContent=`${formatCommitDate(data.buildTime)} · ${formatRelativeTime(data.buildTime)}`;buildTimeEl.title=formatFullDate(data.buildTime);}}
function init(data){window.fmhyData=data;const restoreHistory=new URLSearchParams(window.location.search).get('history')==='1';restoreStateFromUrl();const restoredPage=state.currentPage;initTheme();refreshRelativeTimes();setInterval(refreshRelativeTimes,60000);updateMonthlyToggleUI();const results=document.getElementById('commits-container');results?.addEventListener('click',event=>{const button=event.target.closest('[data-page]');if(button)goToPage(Number(button.dataset.page));});results?.addEventListener('submit',event=>{if(!event.target.matches('.page-jump'))return;event.preventDefault();goToPage(Number(new FormData(event.target).get('page')));});document.getElementById("category-filters")?.addEventListener("click",(e)=>{const button=e.target.closest("[data-category]");if(button)setCategoryFilter(button.dataset.category);});document.getElementById("category-select")?.addEventListener("change",(e)=>setCategoryFilter(e.target.value));document.getElementById("monthly-retry")?.addEventListener("click",()=>{document.getElementById("monthly-toggle").checked=true;toggleMonthlyView();});const starToggle=document.getElementById("star-toggle");if(starToggle){starToggle.addEventListener("click",toggleStarFilter);}
syncStarToggleUI();const themeSelect=document.getElementById("theme-select");if(themeSelect){themeSelect.addEventListener("change",(e)=>setTheme(e.target.value));}
document.querySelectorAll(".stat-filter[data-filter]").forEach((btn)=>{btn.addEventListener("click",()=>setFilter(btn.dataset.filter));const active=btn.dataset.filter===state.currentFilter;btn.classList.toggle("active",active);btn.setAttribute("aria-pressed",String(active));});const searchInput=document.getElementById("search-input");if(searchInput){searchInput.value=state.searchQuery;searchInput.addEventListener("input",handleSearch);}
updateSearchClear();const searchClear=document.getElementById("search-clear");if(searchClear){searchClear.addEventListener("click",clearSearch);}
document.addEventListener("keydown",(e)=>{if(e.key!=="/"||e.ctrlKey||e.metaKey||e.altKey)return;const tag=(e.target.tagName||"").toLowerCase();if(tag==="input"||tag==="textarea"||tag==="select"||e.target.isContentEditable)
return;if(searchInput){e.preventDefault();searchInput.focus();}});const backToTop=document.getElementById("back-to-top");const onScroll=()=>{if(backToTop){backToTop.classList.toggle("visible",window.scrollY>600);}};window.addEventListener("scroll",onScroll,{passive:true});onScroll();if(backToTop){backToTop.addEventListener("click",()=>{window.scrollTo({top:0,behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",});});}
const categoryToggleBtn=document.getElementById("category-toggle-btn");if(categoryToggleBtn){categoryToggleBtn.addEventListener("click",toggleCategoryFilters);}
const monthlyToggle=document.getElementById("monthly-toggle");if(monthlyToggle){monthlyToggle.addEventListener("change",toggleMonthlyView);}
renderCommits({syncUrl:!restoreHistory});if(restoreHistory){document.getElementById('monthly-toggle').checked=true;toggleMonthlyView({restorePage:restoredPage});}}
if(typeof module!=="undefined"&&module.exports){module.exports={init,parseMarkdownLinks,formatRelativeTime,};}