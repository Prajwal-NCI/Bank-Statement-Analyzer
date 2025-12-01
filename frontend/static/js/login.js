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

function showStatus(message, type, statusId) {
  const status = document.getElementById(statusId);
  status.className = 'status ' + type;
  status.textContent = message;
  status.style.display = 'block';
}

function hideStatus(statusId) {
  const elem = document.getElementById(statusId);
  if (elem) elem.style.display = 'none';
}

function showLogin() {
  document.getElementById('loginForm').classList.add('active');
  document.getElementById('forgotPasswordForm').classList.remove('active');
  document.getElementById('resetPasswordForm').classList.remove('active');
  hideStatus('forgotStatus');
  hideStatus('resetStatus');
}

function showForgotPassword() {
  document.getElementById('loginForm').classList.remove('active');
  document.getElementById('forgotPasswordForm').classList.add('active');
  document.getElementById('resetPasswordForm').classList.remove('active');
  hideStatus('loginStatus');
}

function showResetPassword() {
  document.getElementById('loginForm').classList.remove('active');
  document.getElementById('forgotPasswordForm').classList.remove('active');
  document.getElementById('resetPasswordForm').classList.add('active');
  hideStatus('forgotStatus');
}

// Login
document.getElementById('loginBtn').onclick = async function () {
  const email = document.getElementById('loginEmail').value.trim();
  const password = document.getElementById('loginPassword').value;
  const btn = this;

  hideStatus('loginStatus');
  if (!email || !password) {
    showStatus('Please enter email and password', 'error', 'loginStatus');
    return;
  }
  if (!config) {
    showStatus('Loading configuration…', 'info', 'loginStatus');
    await loadConfig();
    if (!config) {
      showStatus('Config load failed', 'error', 'loginStatus');
      return;
    }
  }

  btn.disabled = true;
  btn.textContent = 'Logging in…';

  try {
    const cognitoEndpoint = `https://cognito-idp.${config.cognito.region}.amazonaws.com/`;
    const response = await fetch(cognitoEndpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-amz-json-1.1',
        'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth'
      },
      body: JSON.stringify({
        ClientId: config.cognito.clientId,
        AuthFlow: 'USER_PASSWORD_AUTH',
        AuthParameters: { USERNAME: email, PASSWORD: password }
      })
    });
    const data = await response.json();

    if (response.ok && data.AuthenticationResult) {
      localStorage.setItem('accessToken', data.AuthenticationResult.AccessToken);
      localStorage.setItem('idToken', data.AuthenticationResult.IdToken);
      localStorage.setItem('refreshToken', data.AuthenticationResult.RefreshToken);
      localStorage.setItem('userEmail', email);

      showStatus('Login successful. Redirecting…', 'success', 'loginStatus');
      setTimeout(() => (window.location.href = 'index.html'), 1000);
    } else {
      throw new Error(data.message || 'Login failed');
    }
  } catch (error) {
    showStatus('Error: ' + error.message, 'error', 'loginStatus');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Login';
  }
};

// this part will send code for forgot password
document.getElementById('sendCodeBtn').onclick = async function () {
  const email = document.getElementById('forgotEmail').value.trim();
  const btn = this;

  hideStatus('forgotStatus');
  if (!email) {
    showStatus('Please enter your email', 'error', 'forgotStatus');
    return;
  }
  if (!config) {
    showStatus('Loading configuration…', 'info', 'forgotStatus');
    await loadConfig();
    if (!config) {
      showStatus('Config load failed', 'error', 'forgotStatus');
      return;
    }
  }

  btn.disabled = true;
  btn.textContent = 'Sending code…';

  try {
    const cognitoEndpoint = `https://cognito-idp.${config.cognito.region}.amazonaws.com/`;
    const response = await fetch(cognitoEndpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-amz-json-1.1',
        'X-Amz-Target': 'AWSCognitoIdentityProviderService.ForgotPassword'
      },
      body: JSON.stringify({
        ClientId: config.cognito.clientId,
        Username: email
      })
    });
    const data = await response.json();

    if (response.ok) {
      showStatus('Verification code sent. Check your email.', 'success', 'forgotStatus');
      localStorage.setItem('resetEmail', email);
      setTimeout(showResetPassword, 2000);
    } else {
      throw new Error(data.message || 'Failed to send code');
    }
  } catch (error) {
    showStatus('Error: ' + error.message, 'error', 'forgotStatus');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Send verification code';
  }
};


document.getElementById('resetPasswordBtn').onclick = async function () {
  const code = document.getElementById('verificationCode').value.trim();
  const newPassword = document.getElementById('newPasswordReset').value;
  const confirmPassword = document.getElementById('confirmPasswordReset').value;
  const email = localStorage.getItem('resetEmail');
  const btn = this;

  hideStatus('resetStatus');
  if (!code || !newPassword || !confirmPassword) {
    showStatus('Please fill in all fields', 'error', 'resetStatus');
    return;
  }
  if (newPassword !== confirmPassword) {
    showStatus('Passwords do not match', 'error', 'resetStatus');
    return;
  }
  if (newPassword.length < 8) {
    showStatus('Password must be at least 8 characters', 'error', 'resetStatus');
    return;
  }

  if (!config) {
    showStatus('Loading configuration…', 'info', 'resetStatus');
    await loadConfig();
    if (!config) {
      showStatus('Config load failed', 'error', 'resetStatus');
      return;
    }
  }

  btn.disabled = true;
  btn.textContent = 'Resetting password…';

  try {
    const cognitoEndpoint = `https://cognito-idp.${config.cognito.region}.amazonaws.com/`;
    const response = await fetch(cognitoEndpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-amz-json-1.1',
        'X-Amz-Target': 'AWSCognitoIdentityProviderService.ConfirmForgotPassword'
      },
      body: JSON.stringify({
        ClientId: config.cognito.clientId,
        Username: email,
        ConfirmationCode: code,
        Password: newPassword
      })
    });
    const data = await response.json();

    if (response.ok) {
      showStatus('Password reset successfully. Redirecting to login…', 'success', 'resetStatus');
      localStorage.removeItem('resetEmail');
      setTimeout(showLogin, 2000);
    } else {
      throw new Error(data.message || 'Password reset failed');
    }
  } catch (error) {
    showStatus('Error: ' + error.message, 'error', 'resetStatus');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Reset password';
  }
};

loadConfig();