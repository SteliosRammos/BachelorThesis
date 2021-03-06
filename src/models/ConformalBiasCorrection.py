import pandas as pd
import numpy as np
from imblearn.over_sampling import SMOTE
from nonconformist.icp import IcpClassifier
from nonconformist.nc import NcFactory, MarginErrFunc
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import roc_auc_score, average_precision_score, precision_score, accuracy_score, brier_score_loss, confusion_matrix
from sklearn.model_selection import StratifiedKFold, GridSearchCV

from imblearn.over_sampling import RandomOverSampler
from imblearn.under_sampling import RandomUnderSampler

import matplotlib.pyplot as plt

class ConformalBiasCorrection:

    def __init__(self, train_data, test_data, classifiers, clf_parameters, rebalancing_parameters, bias_correction_parameters, verbose=0, random_state=None):

        self.train_data = train_data
        self.test_data = test_data

        # Defined after self training
        self.augmented_data_lbld = None
        self.augmented_train_data = None

        self.classifiers = classifiers
        self.clf_parameters = clf_parameters
        self.rebalancing_parameters = rebalancing_parameters
        self.bias_correction_parameters = bias_correction_parameters
        self.verbose = verbose
        self.random_state = random_state

    def compute_correction_weights(self):

        if self.verbose >= 2:
            print('Start computing weights W')

        data_s = self.train_data.drop(['uuid', 'finished_treatment'], axis=1)

        # Shuffle rows
        data_s = data_s.sample(frac=1, random_state=self.random_state)
        X = data_s.iloc[:, :-2]
        X = X.fillna(X.mean())

        y = data_s.iloc[:, -1]

        # Startified k-fold
        sss = StratifiedKFold(n_splits=10, random_state=self.random_state)

        if type(y) == np.ndarray:
            prob_s_pos = np.bincount(y)[1] / len(y)
        else:
            prob_s_pos = y.value_counts(True)[1]

        roc_aucs, pr_aucs, brier_losses, best_estimators, splits = [], [], [], [], []
        predicted_prob_s = pd.Series(np.full(y.shape[0], np.nan))
        predicted_prob_s.index = y.index

        fold_num = 0

        for train_index, valid_index in sss.split(X, y):

            X_train, X_valid = X.iloc[train_index], X.iloc[valid_index]
            y_train, y_valid = y.iloc[train_index], y.iloc[valid_index]

            # Fit, calibrate and evaluate the classifier
            classifier_s = self.classifiers['classifier_s']
            parameters = self.clf_parameters['classifier_s']

            best_estimator, roc_auc, pr_auc, brier_loss = self.get_best_estimator(classifier_s, parameters, X_train, X_valid, y_train, y_valid, grid_search=False)

            # Compute weights for test examples
            predicted_prob_s.loc[X_valid.index] = best_estimator.predict_proba(X_valid)[:, 1]

            for index in X_valid.index:
                if predicted_prob_s.loc[index] > 0:
                    self.train_data.loc[index, 'weight'] = prob_s_pos / predicted_prob_s.loc[index]
                else:
                    self.train_data.loc[index, 'weight'] = 0.001/prob_s_pos
            fold_num += 1

            # Store fold results
            if self.verbose >= 3:
                roc_aucs.append(roc_auc)
                pr_aucs.append(pr_auc)
                brier_losses.append(brier_loss)
                best_estimators.append(best_estimator)
                splits.append([train_index, valid_index])

        if self.verbose >= 3:
            print('Classifier S evaluation:')
            print('Average ROC AUC: ', np.array(roc_aucs).mean())
            print('Average PR AUC: ', np.array(pr_aucs).mean())
            print('Average Brier Loss: {} \n'.format(np.array(brier_losses).mean()))

        # Initialize augmented data with weights (in case the self-learning is not applied)
        data_y = self.train_data.drop(['uuid', 'got_go'], axis=1)
        data_lbld = data_y[~data_y.finished_treatment.isna()]
        self.augmented_data_lbld = data_lbld
        self.augmented_train_data = self.train_data

        return np.array(roc_aucs).mean(), np.array(brier_losses).mean()

    def update_correction_weights(self):

        if self.verbose >= 2:
            print('Start computing weights W')

        data_s = self.augmented_train_data.drop(['uuid', 'finished_treatment'], axis=1)

        # Shuffle rows
        data_s = data_s.sample(frac=1, random_state=self.random_state)
        X = data_s.iloc[:, :-2]
        X = X.fillna(X.mean())

        y = data_s.iloc[:, -1]

        # Startified k-fold
        sss = StratifiedKFold(n_splits=10, random_state=self.random_state)

        if type(y) == np.ndarray:
            prob_s_pos = np.bincount(y)[1] / len(y)
        else:
            prob_s_pos = y.value_counts(True)[1]

        roc_aucs, pr_aucs, brier_losses, best_estimators, splits = [], [], [], [], []
        predicted_prob_s = pd.Series(np.full(y.shape[0], np.nan))
        predicted_prob_s.index = y.index

        fold_num = 0

        for train_index, valid_index in sss.split(X, y):

            X_train, X_valid = X.iloc[train_index], X.iloc[valid_index]
            y_train, y_valid = y.iloc[train_index], y.iloc[valid_index]

            # Fit, calibrate and evaluate the classifier
            classifier_s = self.classifiers['classifier_s']
            parameters = self.clf_parameters['classifier_s']

            best_estimator, roc_auc, pr_auc, brier_loss = self.get_best_estimator(classifier_s, parameters, X_train,
                                                                                  X_valid, y_train, y_valid,
                                                                                  grid_search=False)

            # Compute weights for test examples
            predicted_prob_s.loc[X_valid.index] = best_estimator.predict_proba(X_valid)[:, 1]

            for index in X_valid.index:
                if predicted_prob_s.loc[index] > 0:
                    self.train_data.loc[index, 'weight'] = prob_s_pos / predicted_prob_s.loc[index]
                else:
                    self.train_data.loc[index, 'weight'] = 0.001 / prob_s_pos
            fold_num += 1

        # Initialize augmented data with weights (in case the self-learning is not applied)
        data_y = self.train_data.drop(['uuid', 'got_go'], axis=1)
        data_lbld = data_y[~data_y.finished_treatment.isna()]
        self.augmented_data_lbld = data_lbld

        return True

    def visualize_weights(self):

        weights = self.augmented_data_lbld.weight
        plt.hist(weights, bins=100)
        plt.show()

    # Classical semi-supervised learning
    def classic_correct(self):

        data_y = self.train_data.drop(['uuid', 'got_go'], axis=1)

        # Split data into labeled and unlabeled sets
        data_lbld = data_y[~data_y.finished_treatment.isna()]

        data_unlbld = data_y[data_y.finished_treatment.isna()]
        total_unlbld = data_unlbld.shape[0]

        predictions = self.classic_predict(data_lbld, data_unlbld)

        data_unlbld.finished_treatment = predictions

        self.augmented_data_lbld = data_lbld.append(data_unlbld)
        self.augmented_data_lbld

    def classic_predict(self, data_lbld, data_unlbld):
        # Create SMOTE instance for class rebalancing
        smote = SMOTE(random_state=self.random_state)

        # Create instance of classifier
        classifier_y = self.classifiers['classifier_y']
        parameters_y = self.clf_parameters['classifier_y']

        clf = classifier_y.set_params(**parameters_y)

        X = data_lbld.iloc[:, :-2]
        y = data_lbld.iloc[:, -1]

        X_unlbld = data_unlbld.iloc[:, :-2]

        if self.rebalancing_parameters['SMOTE_y']:
            X, y = smote.fit_resample(X, y)
            clf.fit(X[:, :-1], y, sample_weight=X[:, -1])
        else:
            clf.fit(X.iloc[:, :-1], y, sample_weight=X.iloc[:, -1])

        predictions = clf.predict(X_unlbld.iloc[:, :-1])

        return predictions

        # CROSS-VALIDATED CONFORMAL PREDICTIONS

    def ccp_correct(self):

        data_y = self.train_data.drop(['uuid', 'got_go'], axis=1)

        # Split data into labeled and unlabeled sets
        data_lbld = data_y[~data_y["finished_treatment"].isna()]

        data_unlbld = data_y[data_y["finished_treatment"].isna()]
        total_unlbld = data_unlbld.shape[0]

        # Compute positive to negative ratio
        label_cnts = data_lbld["finished_treatment"].value_counts()
        initial_ratio = label_cnts[0] / label_cnts[1]

        if self.rebalancing_parameters['conformal_oversampling']:
            over_sampling_factor = int(label_cnts[1] / label_cnts[0])

        # Initialize array of newly_labeled data
        new_lbld = data_unlbld.copy()
        all_newly_labeled_indeces = []
        last_newly_labeled_indeces = []

        # Initialize stopping variable
        stop = False

        if self.verbose >= 2:
            print('Start conformal improvement.')
            print("Initial unlabeled: {} \n".format(data_unlbld.shape[0]))
            print("Initial ratio: {} \n".format(initial_ratio))

        iterations = 0
        ratio = initial_ratio

        while not stop:
            # Compute weights
            if self.bias_correction_parameters['correct_bias']:
                _, _ = self.compute_correction_weights()

            # Make conformal predictions
            ccp_predictions = self.ccp_predict(data_lbld, data_unlbld, new_lbld.loc[all_newly_labeled_indeces])

            # Add best predictions
            labels = self.get_best_pred_indeces(ccp_predictions, 0.96, ratio)
            new_lbld.loc[labels.index.values, 'finished_treatment'] = labels.values

            # Save new label's indeces
            newly_labeled_indeces = list(labels.index.values)

            if self.rebalancing_parameters['conformal_oversampling']:
                if ratio <= 0.5:
                    oversampled_newly_lbld_indeces = self.oversample_minority(new_lbld, 'finished_treatment', 0,
                                                                              over_sampling_factor,
                                                                              newly_labeled_indeces)
                    all_newly_labeled_indeces += oversampled_newly_lbld_indeces
            else:
                all_newly_labeled_indeces += newly_labeled_indeces

            if self.verbose >= 2:
                print('Number of good predictions: {} \n'.format(labels.shape[0]))

            remain_unlbld = data_unlbld.shape[0]

            ratio = self.calculate_ratio(data_lbld, new_lbld)

            if data_unlbld.shape[0] > 0 and labels.shape[0] > 0 and remain_unlbld > total_unlbld * 0.8 and np.abs(
                    initial_ratio - ratio) < 0.05 * initial_ratio:
                iterations += 1
                last_newly_labeled_indeces = all_newly_labeled_indeces

                data_unlbld = data_unlbld.drop(newly_labeled_indeces)

                if self.verbose >= 2:
                    print("Updated ratio: {} \n".format(ratio))
                    print("Remaining unlabeled: {}".format(data_unlbld.shape[0]))

            else:
                if self.verbose >= 1:
                    print("Condition 1 - Remaining unlabeled > 0: {}".format(data_unlbld.shape[0] > 0))
                    print("Condition 2 - Number of good predictions > 0: {}".format(labels.shape[0] > 0))
                    print("Condition 3 - Percentage labeled >= 20%: {}".format(remain_unlbld > total_unlbld * 0.8))
                    print("Condition 4 - Class ration changed by less than 1%: {}".format(
                        np.abs(initial_ratio - ratio) < 0.05 * initial_ratio))
                    print("Stopping...")

                stop = True

        self.augmented_data_lbld = data_lbld.append(new_lbld.loc[last_newly_labeled_indeces])

    def ccp_predict(self, data_lbld, data_unlbld, new_lbld):

        # Create SMOTE instance for class rebalancing
        smote = SMOTE(random_state=self.random_state)

        # Create instance of classifier
        classifier_y = self.classifiers['classifier_y']
        parameters_y = self.clf_parameters['classifier_y']

        clf = classifier_y.set_params(**parameters_y)

        X = data_lbld.iloc[:, :-2]
        y = data_lbld.iloc[:, -1]

        X_new = new_lbld.iloc[:, :-2]
        y_new = new_lbld.iloc[:, -1]

        X = X.append(X_new, sort=False)
        y = y.append(y_new)

        X_unlbld = data_unlbld.iloc[:, :-2]

        sss = StratifiedKFold(n_splits=5, random_state = self.random_state)
        sss.get_n_splits(X, y)

        p_values = []

        for train_index, calib_index in sss.split(X, y):
            X_train, X_calib = X.iloc[train_index], X.iloc[calib_index]
            y_train, y_calib = y.iloc[train_index], y.iloc[calib_index]

            if self.rebalancing_parameters['SMOTE_y']:
                X_train, y_train = smote.fit_resample(X_train, y_train)
                clf.fit(X_train[:, :-1], y_train, sample_weight=X_train[:, -1])
            else:
                clf.fit(X_train.iloc[:, :-1], y_train, sample_weight=X_train.iloc[:, -1])

            nc = NcFactory.create_nc(clf, MarginErrFunc())
            icp = IcpClassifier(nc)

            if self.rebalancing_parameters['SMOTE_y']:
                icp.fit(X_train[:, :-1], y_train)
            else:
                icp.fit(X_train.iloc[:, :-1].values, y_train)

            icp.calibrate(X_calib.iloc[:, :-1].values, y_calib)

            # Predict confidences for validation sample and unlabeled sample
            p_values.append(icp.predict(X_unlbld.iloc[:, :-1].values, significance=None))

        mean_p_values = np.array(p_values).mean(axis=0)
        ccp_predictions = pd.DataFrame(mean_p_values, columns=['mean_p_0', 'mean_p_1'])
        ccp_predictions["credibility"] = [row.max() for _, row in ccp_predictions.iterrows()]
        ccp_predictions["confidence"] = [1-row.min() for _, row in ccp_predictions.iterrows()]

        ccp_predictions.index = X_unlbld.index

        return ccp_predictions

    def get_best_estimator(self, classifiers_s, parameters, X_train, X_valid, y_train, y_valid, grid_search=False):

        if grid_search:
            skf_5 = StratifiedKFold(5, random_state=self.random_state)
            estimator = GridSearchCV(classifiers_s, param_grid=parameters, cv=skf_5, scoring="roc_auc", verbose=0)

        else:
            estimator = classifiers_s.set_params(**parameters)

        rebalancing = self.rebalancing_parameters['rebalancing_s']

        if rebalancing is not None:
            if rebalancing == 'SMOTE':
                rebalance = SMOTE(0.9, random_state=self.random_state)
            elif rebalancing == 'oversampling':
                rebalance = RandomOverSampler()
            elif rebalancing == 'undersampling':
                rebalance = RandomUnderSampler()

            X_train, y_train = rebalance.fit_resample(X_train, y_train)

        # Calibrate the classifier here
        calib_estimator = CalibratedClassifierCV(estimator, cv=5, method='isotonic')
        calib_estimator.fit(X_train, y_train)

        predicted_proba = calib_estimator.predict_proba(X_valid)[:, 1]
        predicted_labels = calib_estimator.predict(X_valid)
        roc_auc = roc_auc_score(y_valid, predicted_proba)
        pr_auc = average_precision_score(y_valid, predicted_proba)
        brier_loss = brier_score_loss(y_valid, predicted_labels)

        if self.verbose >= 4:
            print(
                'ROC AUC: {0:0.2f} \n'.format(roc_auc),
                'PR AUC: {0:0.2f} \n'.format(pr_auc),
                'Accuracy {0:0.2f} \n '.format(accuracy_score(y_valid, predicted_labels)),
                'Precision {0:0.2f}\n '.format(precision_score(y_valid, predicted_labels)),
                'Brier Loss {0:0.2f}\n '.format(brier_score_loss(y_valid, predicted_labels))
            )

        return calib_estimator, roc_auc, pr_auc, brier_loss

    @staticmethod
    def calculate_ratio(data_lbld, new_lbld):
        data_positives = data_lbld[data_lbld["finished_treatment"] == 1].shape[0]
        data_negatives = data_lbld[data_lbld["finished_treatment"] == 0].shape[0]

        new_positives = new_lbld[new_lbld["finished_treatment"] == 1].shape[0]
        new_negatives = new_lbld[new_lbld["finished_treatment"] == 0].shape[0]

        positives = data_positives + new_positives
        negatives = data_negatives + new_negatives

        ratio = negatives / positives

        return ratio

    def  get_best_pred_indeces(self, predictions, threshold, true_ratio):
        '''
            Returns the predictions that have a confidence level above a given threshold.
            The labels returned will have the same positive/negative ratio as the ratio specified by "true_ratio".
            true_ratio: num_negatives / num_positives
        '''

        predictions['labels'] = [np.argmax(row.values[0:2]) for _, row in predictions.iterrows()]

        positives = predictions[predictions["labels"] == 1].sort_values("mean_p_1")
        negatives = predictions[predictions["labels"] == 0].sort_values("mean_p_0")

        positives = positives.loc[(positives["confidence"] >= threshold) & (positives["credibility"] <= threshold)]
        negatives = negatives.loc[(negatives["confidence"] >= threshold) & (positives["credibility"] <= threshold)]

        current_ratio = (negatives.shape[0] + 1) / (positives.shape[0] + 1)

        if current_ratio < true_ratio:
            while current_ratio < true_ratio and positives.shape[0] > 1:
                positives = positives[1:]
                current_ratio = (negatives.shape[0] + 1) / (positives.shape[0] + 1)

        elif current_ratio > true_ratio:
            while current_ratio > true_ratio and negatives.shape[0] > 1:
                negatives = negatives[1:]
                current_ratio = (negatives.shape[0] + 1) / (positives.shape[0] + 1)

        positives_indeces = list(positives.index.values)
        negatives_indeces = list(negatives.index.values)

        if self.verbose >= 2:
            print("Good positive predictions: {} \n".format(len(positives_indeces)))
            print("Good negative predictions: {} \n".format(len(negatives_indeces)))

        best_pred_indeces = positives_indeces + negatives_indeces
        labels = predictions.loc[best_pred_indeces, "labels"]

        return labels

    def oversample_minority(self, dataframe, label_column, minority_class, factor, at_indeces=None):
        oversampled_indeces = []
        num_oversampled = 0

        if at_indeces is not None:
            for index in at_indeces:
                if dataframe.loc[index, label_column] == minority_class:
                    oversampled_indeces += factor * [index]
                    num_oversampled += 1
                else:
                    oversampled_indeces += [index]
        else:
            for index in dataframe.index:
                if dataframe.loc[index, label_column] == minority_class:
                    oversampled_indeces += factor * [index]
                    num_oversampled += 1
                else:
                    oversampled_indeces += [index]

        if self.verbose >= 2:
            print('Oversampled {} examples by factor of {}.'.format(num_oversampled, factor))

        return oversampled_indeces

    def final_evaluation(self):

        data_y = self.train_data.drop(['uuid', 'got_go'], axis=1)
        data_lbld = data_y[~data_y.finished_treatment.isna()]

        uncorrected_train_data = data_lbld
        corrected_train_data = self.augmented_data_lbld
        test_data = self.test_data

        X_train_uncorrected = uncorrected_train_data.iloc[:, :-1]
        y_train_uncorrected = uncorrected_train_data.iloc[:, -1]

        X_train_corrected = corrected_train_data.iloc[:, :-1]
        y_train_corrected = corrected_train_data.iloc[:, -1]

        test_data = test_data.dropna(subset=['finished_treatment'])
        X_test = test_data.iloc[:, 1:-2]
        y_test = test_data.iloc[:, -1]

        # Create instance of classifier
        counts = uncorrected_train_data.finished_treatment.value_counts()
        ratio = counts[0]/counts[1]

        parameters = self.clf_parameters['classifier_y']
        parameters['scale_pos_weight'] = ratio

        model = self.classifiers['classifier_y']
        model.set_params(**parameters)

        skf_5 = StratifiedKFold(5, random_state=self.random_state)
        calibrated_model = CalibratedClassifierCV(model, cv=skf_5, method='isotonic')

        # Uncorrected model evaluation
        calibrated_model.fit(X_train_uncorrected.iloc[:, :-1], y_train_uncorrected)

        predicted_proba = calibrated_model.predict_proba(X_test.iloc[:, :-1])[:, 1]
        uncorrected_roc_auc = roc_auc_score(y_test.values, predicted_proba)

        predicted_labels = calibrated_model.predict(X_test.iloc[:, :-1])
        uncorrected_confusion_matrix = confusion_matrix(y_test.values, predicted_labels)
        uncorrected_accuracy_score = accuracy_score(y_test.values, predicted_labels)

        if self.verbose >= 1:
            print("Test ROC AUC (not corrected): {}".format(uncorrected_roc_auc))
            # print("Test Confusion matrix (not corrected): \n {} \n".format(uncorrected_confusion_matrix))
            # print("Test accuracy (not corrected): \n {} \n".format(uncorrected_accuracy_score))

        # Corrected model evaluation
        calibrated_model.fit(X_train_corrected.iloc[:, :-1], y_train_corrected, sample_weight=X_train_corrected.iloc[:, -1])
        # feature_importances = model.feature_importances_

        predicted_proba = calibrated_model.predict_proba(X_test.iloc[:, :-1])[:, 1]
        corrected_roc_auc = roc_auc_score(y_test.values, predicted_proba)

        predicted_labels = calibrated_model.predict(X_test.iloc[:, :-1])
        corrected_accuracy_score = accuracy_score(y_test.values, predicted_labels)
        corrected_confusion_matrix = confusion_matrix(y_test.values, predicted_labels)

        if self.verbose >= 1:
            print("Test ROC AUC (corrected): {}".format(corrected_roc_auc))
            # print("Test Confusion matrix (corrected): \n {} \n".format(corrected_confusion_matrix))
            # print("Test accuracy (corrected): \n {} \n".format(corrected_accuracy_score))

        return uncorrected_roc_auc, corrected_roc_auc #, feature_importances

# def evaluate(self, data_lbld, new_lbld):
    #     '''
    #         Evaluate the model with the newly labeled data.
    #         Metric: ROC AUC
    #     '''
    #     # Compute class ratio
    #     ratio = self.calculate_ratio(data_lbld, new_lbld)
    #
    #     # Create instance of classifier
    #     parameters = self.clf_parameters['classifier_y']
    #     parameters['scale_pos_weight'] = ratio
    #
    #     model = self.classifiers['classifier_y']
    #     model.set_params(**parameters)
    #
    #     X = data_lbld.iloc[:, :-1]
    #     y = data_lbld.iloc[:, -1]
    #
    #     # Initialize roc array
    #     roc_aucs = []
    #
    #     skf_10 = StratifiedKFold(10, random_state = self.random_state)
    #     skf_5 = StratifiedKFold(5, random_state = self.random_state)
    #
    #     # Split data into training and validating set
    #     for train_index, valid_index in skf_10.split(X, y):
    #         X_train, X_valid = X.iloc[train_index], X.iloc[valid_index]
    #         y_train, y_valid = y.iloc[train_index], y.iloc[valid_index]
    #
    #         X_new = new_lbld.iloc[:, :-1]
    #         y_new = new_lbld.iloc[:, -1]
    #
    #         X_train = X_train.append(X_new, sort=False)
    #         y_train = y_train.append(y_new)
    #
    #         calibrated_model = CalibratedClassifierCV(model, cv=skf_5, method='isotonic')
    #
    #         # for column in X_train.columns:
    #         #     print(X_train[column].isna().value_counts())
    #
    #         calibrated_model.fit(X_train.iloc[:, :-1], y_train, sample_weight=X_train.iloc[:, -1])
    #         #         calibrated_model.fit(X_train.iloc[:, :-1], y_train)
    #
    #         # Predict labels
    #         predicted_proba = calibrated_model.predict_proba(X_valid.iloc[:, :-1])[:, 1]
    #
    #         # Compute ROC AUC
    #         roc_auc = roc_auc_score(y_valid, predicted_proba)
    #         roc_aucs.append(roc_auc)
    #
    #     avrg_roc = np.array(roc_aucs).mean()
    #
    #     return avrg_roc