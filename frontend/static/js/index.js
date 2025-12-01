let config = null;
const S3_BUCKET = "invoice-management-bucket-prajwal-nci";
let currentAnalysisData = null;
let currentFileName = '';
let lastAnalysisData = { bucket: '', key: '', country: '' };

// This wil show after login
const userEmail = localStorage.getItem('userEmail');
if (userEmail) {
    document.getElementById('userDisplay').textContent = userEmail;
}

// This is for session part
const SESSION_TIMEOUT = 60 * 60 * 1000;
const WARNING_TIME = 5 * 60 * 1000;
let sessionTimer = null;
let warningTimer = null;
let lastActivityTime = Date.now();

function resetSessionTimer() {
    lastActivityTime = Date.now();
    if (sessionTimer) clearTimeout(sessionTimer);
    if (warningTimer) clearTimeout(warningTimer);
    warningTimer = setTimeout(showSessionWarning, SESSION_TIMEOUT - WARNING_TIME);
    sessionTimer = setTimeout(handleSessionExpiry, SESSION_TIMEOUT);
}

function showSessionWarning() {
    const ok = confirm('Your session will expire in 5 minutes due to inactivity.\n\nClick OK to stay logged in.');
    if (ok) refreshAuthToken(); else logout();
}

function handleSessionExpiry() {
    alert('Your session has expired due to inactivity. You will be redirected to login.');
    localStorage.clear();
    window.location.href = 'login.html';
}

async function refreshAuthToken() {
    const refreshToken = localStorage.getItem('refreshToken');
    if (!refreshToken || !config) {
        handleSessionExpiry();
        return;
    }
    try {
        const endpoint = `https://cognito-idp.${config.cognito.region}.amazonaws.com/`;
        const resp = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-amz-json-1.1',
                'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth'
            },
            body: JSON.stringify({
                ClientId: config.cognito.clientId,
                AuthFlow: 'REFRESH_TOKEN_AUTH',
                AuthParameters: { REFRESH_TOKEN: refreshToken }
            })
        });
        const data = await resp.json();
        if (resp.ok && data.AuthenticationResult) {
            localStorage.setItem('accessToken', data.AuthenticationResult.AccessToken);
            localStorage.setItem('idToken', data.AuthenticationResult.IdToken);
            resetSessionTimer();
        } else {
            throw new Error('Token refresh failed');
        }
    } catch (err) {
        console.error('Token refresh error:', err);
        handleSessionExpiry();
    }
}

['mousedown','keydown','scroll','touchstart','click'].forEach(evt => {
    document.addEventListener(evt, () => {
        if (Date.now() - lastActivityTime > 60 * 1000) resetSessionTimer();
    });
});

setInterval(() => {
    const timeLeft = SESSION_TIMEOUT - (Date.now() - lastActivityTime);
    const minutesLeft = Math.max(0, Math.floor(timeLeft / 60000));
    const el = document.getElementById('sessionTimer');
    if (!el) return;
    if (minutesLeft <= 10) {
        el.textContent = minutesLeft > 0 ? `${minutesLeft} minutes left` : '';
        el.style.color = minutesLeft <= 5 ? '#e74c3c' : '#f39c12';
    } else {
        el.textContent = '';
    }
}, 60000);

// this is for config
async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        if (!response.ok) throw new Error('Config load failed');
        config = await response.json();
        if (localStorage.getItem('accessToken')) resetSessionTimer();
    } catch (err) {
        showStatus('Unable to load configuration. Please refresh the page.', 'error');
        console.error('Config error:', err);
    }
}

function logout() {
    if (confirm('Are you sure you want to logout?')) {
        localStorage.clear();
        window.location.href = 'login.html';
    }
}

// This part will help UI
function showStatus(msg, type, id='status') {
    const el = document.getElementById(id);
    el.className = 'status ' + type;
    el.textContent = msg;
    el.style.display = 'block';
}
function hideStatus(id='status') {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
}

function switchTab(name, btn) {
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    document.getElementById(name).classList.add('active');
    btn.classList.add('active');
    if (name === 'saved') loadSavedAnalyses();
}

// this is for settings part email id and password
async function changeEmail() {
    const newEmail = document.getElementById('newEmail').value.trim();
    hideStatus('emailStatus');

    if (!newEmail) {
        showStatus('Please enter a new email address.', 'error', 'emailStatus');
        return;
    }
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!re.test(newEmail)) {
        showStatus('Please enter a valid email address.', 'error', 'emailStatus');
        return;
    }
    const accessToken = localStorage.getItem('accessToken');
    if (!accessToken) {
        showStatus('Not authenticated. Please login again.', 'error', 'emailStatus');
        return;
    }
    if (!config) {
        showStatus('Configuration not loaded. Please refresh the page.', 'error', 'emailStatus');
        return;
    }
    try {
        showStatus('Updating email address...', 'info', 'emailStatus');
        const endpoint = `https://cognito-idp.${config.cognito.region}.amazonaws.com/`;
        const resp = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-amz-json-1.1',
                'X-Amz-Target': 'AWSCognitoIdentityProviderService.UpdateUserAttributes'
            },
            body: JSON.stringify({
                AccessToken: accessToken,
                UserAttributes: [{ Name: 'email', Value: newEmail }]
            })
        });
        const data = await resp.json();
        if (resp.ok) {
            showStatus('Email updated. You may need to verify the new email.', 'success', 'emailStatus');
            localStorage.setItem('userEmail', newEmail);
            document.getElementById('userDisplay').textContent = newEmail;
            document.getElementById('newEmail').value = '';
        } else {
            throw new Error(data.message || 'Failed to update email');
        }
    } catch (err) {
        showStatus('Error: ' + err.message, 'error', 'emailStatus');
        console.error('Email update error:', err);
    }
}

async function changePassword() {
    const oldPw = document.getElementById('oldPassword').value;
    const newPw = document.getElementById('newPassword').value;
    const confirmPw = document.getElementById('confirmPassword').value;
    hideStatus('passwordStatus');

    if (!oldPw || !newPw || !confirmPw) {
        showStatus('Please fill in all password fields.', 'error', 'passwordStatus');
        return;
    }
    if (newPw !== confirmPw) {
        showStatus('New passwords do not match.', 'error', 'passwordStatus');
        return;
    }
    if (newPw.length < 8) {
        showStatus('Password must be at least 8 characters long.', 'error', 'passwordStatus');
        return;
    }
    const accessToken = localStorage.getItem('accessToken');
    if (!accessToken) {
        showStatus('Not authenticated. Please login again.', 'error', 'passwordStatus');
        return;
    }
    if (!config) {
        showStatus('Configuration not loaded. Please refresh the page.', 'error', 'passwordStatus');
        return;
    }
    try {
        showStatus('Changing password...', 'info', 'passwordStatus');
        const endpoint = `https://cognito-idp.${config.cognito.region}.amazonaws.com/`;
        const resp = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-amz-json-1.1',
                'X-Amz-Target': 'AWSCognitoIdentityProviderService.ChangePassword'
            },
            body: JSON.stringify({
                AccessToken: accessToken,
                PreviousPassword: oldPw,
                ProposedPassword: newPw
            })
        });
        const data = await resp.json();
        if (resp.ok) {
            showStatus('Password changed successfully.', 'success', 'passwordStatus');
            document.getElementById('oldPassword').value = '';
            document.getElementById('newPassword').value = '';
            document.getElementById('confirmPassword').value = '';
        } else {
            throw new Error(data.message || 'Failed to change password');
        }
    } catch (err) {
        showStatus('Error: ' + err.message, 'error', 'passwordStatus');
        console.error('Password change error:', err);
    }
}

// this will save current analysis
async function saveCurrentAnalysis() {
    hideStatus('saveStatus');
    if (!currentAnalysisData) {
        showStatus('No analysis to save. Please analyze a statement first.', 'warning', 'saveStatus');
        return;
    }
    const email = localStorage.getItem('userEmail');
    if (!email) {
        showStatus('Not authenticated. Please login again.', 'error', 'saveStatus');
        return;
    }
    try {
        showStatus('Saving analysis...', 'info', 'saveStatus');
        const resp = await fetch(config.api.baseUrl + "/bank/save-analysis", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user_email: email,
                analysis_data: currentAnalysisData,
                file_name: currentFileName
            })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Failed to save analysis');
        if (data.is_duplicate) {
            showStatus(`This analysis was already saved on ${data.saved_at_formatted}.`, 'info', 'saveStatus');
        } else {
            showStatus(`Analysis saved on ${data.saved_at_formatted}.`, 'success', 'saveStatus');
        }
    } catch (err) {
        showStatus('Error: ' + err.message, 'error', 'saveStatus');
        console.error('Save error:', err);
    }
}

// this will load or delete analyses
async function loadSavedAnalyses() {
    const email = localStorage.getItem('userEmail');
    const listDiv = document.getElementById('savedAnalysesList');
    hideStatus('savedStatus');

    if (!email) {
        showStatus('Not authenticated. Please login again.', 'error', 'savedStatus');
        return;
    }

    try {
        showStatus('Loading saved analyses...', 'info', 'savedStatus');
        const resp = await fetch(config.api.baseUrl + "/bank/my-analyses", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_email: email })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Failed to load analyses');

        if (data.count === 0) {
            listDiv.innerHTML =
                '<p class="placeholder">No saved analyses yet. Save an analysis from the Overview tab.</p>';
            hideStatus('savedStatus');
            return;
        }

        hideStatus('savedStatus');
        let html = '<div style="margin-top: 10px;">';

        data.analyses.forEach(analysis => {
            const analysisStr = JSON.stringify(analysis)
                .replace(/'/g, "'").replace(/"/g, '&quot;');
            html += `
                <div class="category-section" style="margin-bottom: 16px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <div>
                            <h3 style="margin: 0; color: #111827;">${analysis.file_name}</h3>
                            <p style="margin: 5px 0; color: #6b7280; font-size: 0.9em;">
                                Saved: ${analysis.saved_at_formatted} | Country: ${analysis.country_code}
                            </p>
                        </div>
                        <div style="display:flex; gap:8px;">
                            <button class="btn btn-primary"
                                    onclick='viewAnalysis(${analysisStr})'
                                    style="width: auto; padding: 10px 16px;">
                                View
                            </button>
                            <button class="btn btn-danger"
                                    onclick="deleteSavedAnalysis('${analysis.analysis_id}')"
                                    style="width: auto; padding: 10px 16px;">
                                Delete
                            </button>
                        </div>
                    </div>

                    <div class="summary-grid">
                        <div class="summary-card">
                            <div class="label">Total spent</div>
                            <div class="value">€${analysis.total_gross.toFixed(2)}</div>
                        </div>
                        <div class="summary-card">
                            <div class="label">Net amount</div>
                            <div class="value">€${analysis.total_net.toFixed(2)}</div>
                        </div>
                        <div class="summary-card">
                            <div class="label">VAT paid</div>
                            <div class="value">€${analysis.total_vat.toFixed(2)}</div>
                        </div>
                        <div class="summary-card">
                            <div class="label">Transactions</div>
                            <div class="value">${analysis.transaction_count}</div>
                        </div>
                    </div>
                </div>
            `;
        });

        html += '</div>';
        listDiv.innerHTML = html;
    } catch (err) {
        showStatus('Error: ' + err.message, 'error', 'savedStatus');
        console.error('Load error:', err);
    }
}

async function deleteSavedAnalysis(analysisId) {
    const email = localStorage.getItem('userEmail');
    if (!confirm('Delete this saved analysis permanently?')) return;
    if (!email) {
        showStatus('Not authenticated. Please login again.', 'error', 'savedStatus');
        return;
    }
    try {
        showStatus('Deleting analysis...', 'info', 'savedStatus');
        const resp = await fetch(config.api.baseUrl + "/bank/delete-analysis", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_email: email, analysis_id: analysisId })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Failed to delete analysis');
        showStatus('Analysis deleted.', 'success', 'savedStatus');
        await loadSavedAnalyses();
    } catch (err) {
        showStatus('Error: ' + err.message, 'error', 'savedStatus');
        console.error('Delete analysis error:', err);
    }
}

// this part will help to view saved analysis
function viewAnalysis(analysis) {
    const analysisData = {
        country_code: analysis.country_code,
        transaction_count: analysis.transaction_count,
        monthly_summary: analysis.monthly_summary,
        category_summary: analysis.category_summary
    };
    displayResults(analysisData);
    const firstTab = document.querySelector('.tab');
    if (firstTab) switchTab('overview', firstTab);
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

document.getElementById('analyzeBtn').onclick = async function() {
    const fileInput = document.getElementById("fileInput");
    const country = document.getElementById('countrySelect').value;
    const deleteSection = document.getElementById('deleteSection');
    const btn = this;

    hideStatus();
    hideStatus('deleteStatus');
    deleteSection.style.display = 'none';

    const file = fileInput.files[0];
    if (!file) {
        showStatus("Please select a PDF file.", 'error');
        return;
    }
    if (!file.name.toLowerCase().endsWith('.pdf')) {
        showStatus("File must be a PDF. Please use your official bank statement PDF.", 'error');
        return;
    }

    if (!config) {
        showStatus('Loading configuration...', 'info');
        await loadConfig();
        if (!config) {
            showStatus('Configuration not available. Please refresh the page.', 'error');
            return;
        }
    }

    btn.disabled = true;
    btn.textContent = 'Uploading...';

    try {
        const timestamp = Date.now();
        const s3Key = 'statements/' + timestamp + '-' + file.name.replace(/\s/g, '-');

        const reader = new FileReader();
        reader.onload = async e => {
            const base64Content = e.target.result.split(',')[1];

            const uploadResp = await fetch(config.api.baseUrl + "/upload", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    filename: s3Key,
                    content: base64Content,
                    contentType: file.type
                })
            });
            if (!uploadResp.ok) {
                const err = await uploadResp.json().catch(() => ({}));
                throw new Error(err.error || "Upload failed");
            }

            btn.textContent = 'Analyzing...';
            showStatus('File uploaded. Analyzing statement...', 'info');

            const email = localStorage.getItem('userEmail');

            const analyzeResp = await fetch(config.api.baseUrl + "/bank/analyze", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    bucket: S3_BUCKET,
                    key: s3Key,
                    country_code: country,
                    user_email: email
                })
            });

            const analyzeData = await analyzeResp.json();
            if (!analyzeResp.ok) {
                throw new Error(analyzeData.error || "Analysis failed. Make sure the PDF is a bank statement, not another type of PDF.");
            }

            lastAnalysisData = { bucket: S3_BUCKET, key: s3Key, country };
            currentAnalysisData = analyzeData;
            currentFileName = file.name;

            displayResults(analyzeData);
            showStatus('Analysis complete.', 'success');
            deleteSection.style.display = 'block';
        };

        reader.readAsDataURL(file);
    } catch (err) {
        showStatus('Error: ' + err.message, 'error');
        console.error(err);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Upload and analyze';
    }
};

// This part will file from s3
document.getElementById('deleteBtn').onclick = async function() {
    if (!lastAnalysisData.key) {
        showStatus('No file to delete.', 'warning', 'deleteStatus');
        return;
    }
    if (!confirm('Are you sure you want to delete this file from storage?')) return;
    try {
        showStatus('Deleting file...', 'info', 'deleteStatus');
        const resp = await fetch(config.api.baseUrl + "/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                bucket: lastAnalysisData.bucket,
                key: lastAnalysisData.key
            })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Delete failed");
        showStatus('File deleted successfully.', 'success', 'deleteStatus');
        lastAnalysisData = { bucket: '', key: '', country: '' };
    } catch (err) {
        showStatus('Error: ' + err.message, 'error', 'deleteStatus');
        console.error(err);
    }
};

// This will display result
function displayResults(data) {
    const monthly = data.monthly_summary || {};
    const categories = data.category_summary || {};

    let totalNet = 0, totalVAT = 0, totalGross = 0;
    Object.values(monthly).forEach(m => {
        totalNet  += m.net_total   || 0;
        totalVAT  += m.vat_total   || 0;
        totalGross+= m.gross_total || 0;
    });

    const overviewDiv = document.getElementById('overview');
    overviewDiv.innerHTML = `
        <h2>Summary</h2>
        <div class="summary-grid">
            <div class="summary-card">
                <div class="label">Total spent</div>
                <div class="value">€${totalGross.toFixed(2)}</div>
            </div>
            <div class="summary-card">
                <div class="label">Net amount</div>
                <div class="value">€${totalNet.toFixed(2)}</div>
            </div>
            <div class="summary-card">
                <div class="label">VAT paid</div>
                <div class="value">€${totalVAT.toFixed(2)}</div>
            </div>
            <div class="summary-card">
                <div class="label">Transactions</div>
                <div class="value">${data.transaction_count || 0}</div>
            </div>
        </div>

        <button class="btn btn-primary" onclick="saveCurrentAnalysis()" style="margin-top: 20px;">
            Save this analysis
        </button>
        <div class="status" id="saveStatus"></div>
    `;

    const monthlyDiv = document.getElementById('monthly');
    if (!Object.keys(monthly).length) {
        monthlyDiv.innerHTML = '<p class="placeholder">No monthly data available yet.</p>';
    } else {
        let mHtml = '<h2>Monthly breakdown</h2>';
        Object.entries(monthly).sort().forEach(([month, mData]) => {
            mHtml += `
                <div class="category-section">
                    <div class="category-header">
                        <span class="category-name">${month}</span>
                        <span class="category-total">€${mData.gross_total.toFixed(2)}</span>
                    </div>
                    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 15px;">
                        <div><strong>Net:</strong> €${mData.net_total.toFixed(2)}</div>
                        <div><strong>VAT:</strong> €${mData.vat_total.toFixed(2)}</div>
                        <div><strong>Total:</strong> €${mData.gross_total.toFixed(2)}</div>
                    </div>
                    <h4>By category</h4>
            `;
            Object.entries(mData.by_category || {}).forEach(([cat, amount]) => {
                mHtml += `
                    <div class="month-row">
                        <span class="month-name">${cat}</span>
                        <span class="month-amount">€${amount.toFixed(2)}</span>
                    </div>
                `;
            });
            mHtml += '</div>';
        });
        monthlyDiv.innerHTML = mHtml;
    }


    const categoryDiv = document.getElementById('category');
    if (!Object.keys(categories).length) {
        categoryDiv.innerHTML = '<p class="placeholder">No category data available yet.</p>';
    } else {
        let cHtml = '<h2>Category breakdown</h2>';
        Object.entries(categories).forEach(([category, catData]) => {
            cHtml += `
                <div class="category-section">
                    <div class="category-header">
                        <span class="category-name">${category}</span>
                        <span class="category-total">€${catData.gross.toFixed(2)}</span>
                    </div>
                    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 15px;">
                        <div><strong>Count:</strong> ${catData.count}</div>
                        <div><strong>Net:</strong> €${catData.net.toFixed(2)}</div>
                        <div><strong>VAT:</strong> €${catData.vat.toFixed(2)}</div>
                        <div><strong>Total:</strong> €${catData.gross.toFixed(2)}</div>
                    </div>
                    <h4>By month</h4>
                    <div class="month-breakdown">
            `;
            Object.entries(catData.by_month || {}).sort().forEach(([month, mData]) => {
                cHtml += `
                    <div class="month-row">
                        <span class="month-name">${month}</span>
                        <span class="month-amount">
                            €${mData.gross.toFixed(2)}
                            <span class="vat-info">(Net: €${mData.net.toFixed(2)}, VAT: €${mData.vat.toFixed(2)})</span>
                        </span>
                    </div>
                `;
            });
            cHtml += `
                    </div>
                </div>
            `;
        });
        categoryDiv.innerHTML = cHtml;
    }
}

window.addEventListener('load', loadConfig);