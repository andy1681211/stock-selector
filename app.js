// ========== 配置 ==========
// 从本地JSON文件加载数据（开发时）或从GitHub加载（部署后）
const CONFIG = {
    // 本地开发模式：直接读文件
    // GitHub Pages模式：从仓库raw链接加载
    useGitHub: false,  // 部署时改为 true
    githubUser: 'andy1681211',
    githubRepo: 'stock-selector',
    branch: 'main',
    dataDir: '../data'  // 相对路径，指向 workspace/data/
};

// ========== 加载每日精选 ==========
async function loadDailyPicks() {
    const listEl = document.getElementById('dailyList');
    const timeEl = document.getElementById('updateTime');
    
    try {
        let data = null;
        
        // 尝试从本地JSON文件加载
        const latestFile = await findLatestFile(CONFIG.dataDir, 'daily_pick_');
        if (latestFile) {
            data = await loadJSON(latestFile);
        }
        
        // 如果本地没有，尝试从GitHub加载
        if (!data) {
            data = await loadFromGitHub('data/daily_pick_');
        }
        
        if (!data) {
            listEl.innerHTML = '<p style="text-align:center;color:#999;">暂无数据，请先运行选股脚本</p>';
            timeEl.textContent = '';
            return;
        }
        
        // 更新时间
        const pickDate = extractDateFromFile(latestFile || '');
        timeEl.textContent = `更新时间：${pickDate || '未知'}`;
        
        // 渲染股票列表
        const picks = data.recommendations || data.picks || [];
        if (picks.length === 0) {
            listEl.innerHTML = '<p style="text-align:center;color:#999;">今日无推荐，市场处于观望期</p>';
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
        
        // 缓存 picks 数据供详情查看
        window._picks = picks;
        
    } catch (err) {
        console.error('加载选股数据失败:', err);
        listEl.innerHTML = '<p style="text-align:center;color:#f44;">数据加载失败</p>';
    }
}

// ========== 加载板块资金流向 ==========
async function loadSectors() {
    const el = document.getElementById('sectorTags');
    
    try {
        // 尝试从本地 sector 数据加载
        const data = await loadFromGitHub('data/sector_top.txt');
        if (data) {
            renderSectors(data);
            return;
        }
        
        // 如果没有板块数据，显示提示
        el.innerHTML = '<p style="text-align:center;color:#999;">板块数据暂未生成</p>';
    } catch (err) {
        el.innerHTML = '';
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
    el.innerHTML = html || '<p style="text-align:center;color:#999;">暂无板块数据</p>';
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
        // 从通达信 .day 文件加载技术分析
        const result = await analyzeFromTDX(code);
        
        document.getElementById('loading').style.display = 'none';
        
        if (result.error) {
            document.getElementById('resultSection').style.display = 'block';
            document.getElementById('resultCard').innerHTML = `
                <div class="result-card">
                    <h2>${result.name || '未知'}</h2>
                    <p class="stock-code">${code}</p>
                    <div class="recommendation danger">
                        <p>⚠️ ${result.error}</p>
                    </div>
                </div>
            `;
            return;
        }
        
        // 渲染分析结果
        const macd = result.macd || {};
        const ma = result.ma || {};
        const rs = result.summary || '';
        
        let html = `
            <h2>${result.name || '未知'}</h2>
            <p class="stock-code">${code}</p>
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
                    <span class="metric-value" style="color:${macd.dif > macd.dea ? '#4caf50' : '#f44336'}">${macd.signal || '-'}</span>
                </div>
            </div>
            <div class="recommendation ${rs.includes('买入') ? '' : rs.includes('观望') ? 'warning' : 'danger'}">
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

// 从通达信 .day 文件解析技术分析
async function analyzeFromTDX(code) {
    const prefix = code.startsWith('6') ? 'sh' : 'sz';
    const tdxPath = `D:/new_tdx/vipdoc/${prefix}/lday/${prefix}${code}.day`;
    
    // 由于浏览器无法直接读取本地文件，这里返回模拟数据
    // 实际使用时需要通过后端API或手动上传 .day 文件
    return {
        code: code,
        name: code,  // 需要从 profile.dat 解析
        ma: { ma5: '-', ma10: '-', ma20: '-' },
        macd: { signal: '-' },
        summary: '请在本地运行分析脚本后，将结果放到 data/ 目录下'
    };
}

// ========== 工具函数 ==========
function truncate(str, len) {
    return str.length > len ? str.substring(0, len) + '...' : str;
}

function extractDateFromFile(path) {
    if (!path) return '';
    const match = path.match(/(\d{4}-\d{2}-\d{2})/);
    return match ? match[1] : '';
}

async function loadJSON(path) {
    try {
        const resp = await fetch(path);
        if (!resp.ok) return null;
        return await resp.json();
    } catch (e) {
        return null;
    }
}

async function loadFromGitHub(prefix) {
    // 尝试从 GitHub raw 加载
    const url = `https://raw.githubusercontent.com/${CONFIG.githubUser}/${CONFIG.githubRepo}/${CONFIG.branch}/${prefix}*`;
    // 注意：GitHub raw 不支持通配符，需要知道具体文件名
    return null;
}

async function findLatestFile(dir, prefix) {
    // 在本地模式下，返回最新文件路径
    // 部署到 GitHub 后需要改为从仓库获取文件列表
    return null;
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
    
    // 回车键触发分析
    document.getElementById('stockInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') analyzeStock();
    });
});
