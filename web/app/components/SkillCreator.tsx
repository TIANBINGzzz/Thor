"use client";

import { useState } from "react";

export interface SkillCreatorProps {
  onClose: () => void;
  onSubmit: (name: string, description: string, scenarios: string) => void;
}

export function SkillCreator({ onClose, onSubmit }: SkillCreatorProps) {
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [scenarios, setScenarios] = useState("");
  const [nameError, setNameError] = useState("");

  function validateName(value: string): boolean {
    if (!value) {
      setNameError("名称不能为空");
      return false;
    }
    if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(value)) {
      setNameError("只能包含小写字母、数字和连字符");
      return false;
    }
    setNameError("");
    return true;
  }

  function handleNext() {
    if (step === 1) {
      if (!validateName(name)) return;
      setStep(2);
    } else if (step === 2) {
      if (!description.trim()) return;
      setStep(3);
    }
  }

  function handleSubmit() {
    if (name && description) {
      onSubmit(name, description, scenarios);
    }
  }

  const canProceed = step === 1 ? name && !nameError : step === 2 ? description.trim() : true;

  return (
    <div className="skill-creator-backdrop" onClick={onClose}>
      <div className="skill-creator-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="skill-creator-header">
          <h3>创建新 Skill</h3>
          <div className="skill-creator-steps">
            <span data-active={step >= 1}>1</span>
            <span data-active={step >= 2}>2</span>
            <span data-active={step >= 3}>3</span>
          </div>
        </div>

        <div className="skill-creator-content">
          {step === 1 && (
            <div className="skill-creator-step">
              <label>
                <strong>Skill 名称</strong>
                <small>使用 kebab-case，如 api-test</small>
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => {
                  setName(e.target.value.toLowerCase());
                  setNameError("");
                }}
                onBlur={(e) => validateName(e.target.value)}
                placeholder="my-skill"
                autoFocus
              />
              {nameError && <p className="error-text">{nameError}</p>}
            </div>
          )}

          {step === 2 && (
            <div className="skill-creator-step">
              <label>
                <strong>描述</strong>
                <small>一句话说明这个 Skill 的用途</small>
              </label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="用于..."
                autoFocus
              />
            </div>
          )}

          {step === 3 && (
            <div className="skill-creator-step">
              <label>
                <strong>使用场景</strong>
                <small>什么情况下会用到这个 Skill（可选）</small>
              </label>
              <textarea
                value={scenarios}
                onChange={(e) => setScenarios(e.target.value)}
                placeholder="例如：需要分析大量数据时..."
                rows={4}
                autoFocus
              />
              <div className="skill-creator-preview">
                <strong>预览</strong>
                <div className="preview-box">
                  <p><strong>名称:</strong> {name}</p>
                  <p><strong>描述:</strong> {description}</p>
                  {scenarios && <p><strong>场景:</strong> {scenarios}</p>}
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="skill-creator-actions">
          {step > 1 && (
            <button type="button" onClick={() => setStep(step - 1)} className="btn-secondary">
              上一步
            </button>
          )}
          {step < 3 ? (
            <button type="button" onClick={handleNext} className="btn-primary" disabled={!canProceed}>
              下一步
            </button>
          ) : (
            <button type="button" onClick={handleSubmit} className="btn-primary" disabled={!canProceed}>
              创建
            </button>
          )}
          <button type="button" onClick={onClose} className="btn-text">
            取消
          </button>
        </div>
      </div>
    </div>
  );
}
