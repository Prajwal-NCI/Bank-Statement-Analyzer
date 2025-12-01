let config = null;

async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        if (!response.ok) throw new Error('Config load failed');
        config = await response.json();
        console.log('Config loaded:', config);
    } catch (error) {
        console.error('Config error:', error);
    }
}

function showStatus(message, type) {
    const status = document.getElementById('status');
    status.className = 'status ' + type;
    status.textContent = message;
    status.style.display = 'block';
}

function hideStatus() {
    document.getElementById('status').style.display = 'none';
}

document.getElementById('signupBtn').onclick = async function() {
    const email = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;
    const confirmPassword = document.getElementById('confirmPassword').value;
    const btn = this;
    
    hideStatus();
    
    if (!email || !password || !confirmPassword) {
        showStatus('Please fill in all fields.', 'error');
        return;
    }
    
    if (password !== confirmPassword) {
        showStatus('Passwords do not match.', 'error');
        return;
    }
    
    if (password.length < 8) {
        showStatus('Password must be at least 8 characters.', 'error');
        return;
    }
    
    if (!config) {
        showStatus('Loading configuration...', 'info');
        await loadConfig();
        if (!config) {
            showStatus('Configuration is not available. Please refresh the page and try again.', 'error');
            return;
        }
    }
    
    btn.disabled = true;
    btn.textContent = 'Creating account...';
    
    try {
        const cognitoEndpoint = `https://cognito-idp.${config.cognito.region}.amazonaws.com/`;
        
        const response = await fetch(cognitoEndpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-amz-json-1.1',
                'X-Amz-Target': 'AWSCognitoIdentityProviderService.SignUp'
            },
            body: JSON.stringify({
                ClientId: config.cognito.clientId,
                Username: email,
                Password: password,
                UserAttributes: [
                    { Name: 'email', Value: email }
                ]
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showStatus('Your account has been created. Please check your email for a verification code.', 'success');
            
            setTimeout(() => {
                window.location.href = 'login.html';
            }, 3000);
        } else {
            throw new Error(data.message || 'Sign up failed.');
        }
        
    } catch (error) {
        showStatus('Error: ' + error.message, 'error');
        console.error('Signup error:', error);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Sign up';
    }
};

loadConfig();