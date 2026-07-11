// ========== 配置 ==========
const CONFIG = {
    githubUser: 'andy1681211',
    githubRepo: 'stock-selector',
    branch: 'main',
    docsFolder: 'docs'
};

function rawUrl(path) {
    return `https://raw.githubusercontent.com/${CONFIG.githubUser}/${CONFIG.githubRepo}/${CONFIG.branch}/${path}`;
}

// ========== 加载每日精选 ==========
async function loadDailyPicks() {
    const listEl = document.getElementById('dailyList');
    const timeEl = document.getElementById('updateTime');
    
    try {
        const url = rawUrl(`${CONFIG.docsFolder}/data/latest_pick.json`);
        const resp = await fetch(url);
        if (!resp.ok) {
            throw new Error('数据文件不存在');
        }
        const data = await resp.json();
        
        // 更新时间
        if (data.date) {
            timeEl.textContent = `更新时间：${data.date}`;
        }
        
        const picks = data.recommendations || [];
        if (picks.length === 0) {
            listEl.innerHTML = '<p style="text-align:center;color:#ccc;">今日无推荐，市场处于观望期</p>';
            return;
        }
        
        let html = '';
        picks.forEach((pick, i) => {
            const code = pick.code || pick.stock_code || '';
            const name = pick.name || pick.stock_name || '';
            const score = pick.score || pick.total_score || '-';
            const reason = pick.reason || pick.analysis || '';
            
            html += `
                <div class="stock-item" onclick="showDetail(${i})">
                    <div class="stock-info">
                        <div class="stock-name">${name}</div>
                        <div class="stock-code-small">${code}</div>
                        ${reason ? `<div style="font-size:0.8em;color:#888;margin-top:4px;">${truncate(reason, 60)}</div>` : ''}
                    </div>
                    <div class="stock-score">${score}</div>
                </div>
            `;
        });
        
        listEl.innerHTML = html;
        window._picks = picks;
        
    } catch (err) {
        console.error('加载选股数据失败:', err);
        listEl.innerHTML = '<p style="text-align:center;color:#f44;">暂无数据，请先运行选股脚本</p>';
        timeEl.textContent = '';
    }
}

// ========== 加载板块资金流向 ==========
async function loadSectors() {
    const el = document.getElementById('sectorTags');
    
    try {
        const url = rawUrl(`${CONFIG.docsFolder}/data/sectors.txt`);
        const resp = await fetch(url);
        if (!resp.ok) {
            el.innerHTML = '<p style="text-align:center;color:#ccc;">板块数据暂未生成</p>';
            return;
        }
        const text = await resp.text();
        renderSectors(text);
    } catch (err) {
        el.innerHTML = '<p style="text-align:center;color:#ccc;">板块数据暂未生成</p>';
    }
}

function renderSectors(text) {
    const el = document.getElementById('sectorTags');
    const lines = text.split('\n').filter(l => l.trim());
    
    let html = '';
    lines.slice(0, 15).forEach(line => {
        const sector = line.replace(/^\d+\./, '').trim();
        if (sector) {
            html += `<span class="sector-tag">${sector}</span>`;
        }
    });
    el.innerHTML = html || '<p style="text-align:center;color:#ccc;">暂无板块数据</p>';
}

// ========== 个股技术分析 ==========
async function analyzeStock() {
    const code = document.getElementById('stockInput').value.trim();
    if (!code || code.length !== 6) {
        alert('请输入6位股票代码');
        return;
    }
    
    document.getElementById('loading').style.display = 'block';
    document.getElementById('resultSection').style.display = 'none';
    
    try {
        // 尝试从 tdx_analysis 数据文件加载
        const dateStr = new Date().toISOString().split('T')[0];
        const url = rawUrl(`data/tdx_analysis_${code}_${dateStr}.json`);
        
        let result = null;
        try {
            const resp = await fetch(url);
            if (resp.ok) {
                result = await resp.json();
            }
        } catch(e) {}
        
        // 如果没有当天数据，尝试最近一次的分析
        if (!result) {
            const allFiles = [
                rawUrl(`data/tdx_analysis_${code}_2026-07-08.json`),
                rawUrl(`data/tdx_analysis_${code}_2026-07-01.json`),
            ];
            for (const u of allFiles) {
                try {
                    const resp = await fetch(u);
                    if (resp.ok) {
                        result = await resp.json();
                        break;
                    }
                } catch(e) {}
            }
        }
        
        document.getElementById('loading').style.display = 'none';
        
        if (!result) {
            document.getElementById('resultSection').style.display = 'block';
            document.getElementById('resultCard').innerHTML = `
                <h2>${code}</h2>
                <p class="stock-code">${code}</p>
                <div class="recommendation warning">
                    <p>📊 暂无技术分析数据。请在本地运行选股脚本后同步数据。</p>
                </div>
            `;
            return;
        }
        
        // 渲染分析结果
        const ma = result.ma || {};
        const macd = result.macd || {};
        const rs = result.summary || '';
        
        let html = `
            <h2>${result.stock?.name || result.name || code}</h2>
            <p class="stock-code">${result.stock?.code || code}</p>
            <div class="metrics-grid">
                <div class="metric-item">
                    <span class="metric-label">MA5</span>
                    <span class="metric-value">${ma.ma5 || '-'}</span>
                </div>
                <div class="metric-item">
                    <span class="metric-label">MA10</span>
                    <span class="metric-value">${ma.ma10 || '-'}</span>
                </div>
                <div class="metric-item">
                    <span class="metric-label">MA20</span>
                    <span class="metric-value">${ma.ma20 || '-'}</span>
                </div>
                <div class="metric-item">
                    <span class="metric-label">MACD</span>
                    <span class="metric-value">${macd.signal || '-'}</span>
                </div>
            </div>
            <div class="recommendation ${rs.includes('买入') ? '' : rs.includes('观望') ? 'warning' : ''}">
                <p>📊 ${rs || '分析完成'}</p>
            </div>
        `;
        
        document.getElementById('resultSection').style.display = 'block';
        document.getElementById('resultCard').innerHTML = html;
        
    } catch (err) {
        document.getElementById('loading').style.display = 'none';
        document.getElementById('resultSection').style.display = 'block';
        document.getElementById('resultCard').innerHTML = `
            <div class="recommendation danger">
                <p>❌ 分析失败：${err.message}</p>
            </div>
        `;
    }
}

// ========== 工具函数 ==========
function truncate(str, len) {
    return str.length > len ? str.substring(0, len) + '...' : str;
}

function showDetail(index) {
    if (!window._picks || !window._picks[index]) return;
    const pick = window._picks[index];
    alert(`${pick.name || pick.stock_name}\n代码：${pick.code || pick.stock_code}\n评分：${pick.score || pick.total_score}\n分析：${pick.reason || pick.analysis || '暂无'}`);
}

// ========== 初始化 ==========
document.addEventListener('DOMContentLoaded', () => {
    loadDailyPicks();
    loadSectors();
    
    document.getElementById('stockInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') analyzeStock();
    });
});
